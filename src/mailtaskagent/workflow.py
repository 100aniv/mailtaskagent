from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from mailtaskagent.config import Settings
from mailtaskagent.decision import build_guarded_agent_proposal, decide_action
from mailtaskagent.llm_client import MailAnalyzer
from mailtaskagent.models import (
    ActionProposal,
    AgentAction,
    GuardedActionResult,
    GuardVerdict,
    MailAnalysis,
    MailInput,
    MailIntent,
    ReviewDecision,
    TaskCandidate,
    TaskContextDecision,
    TaskRelation,
    WorkflowResult,
)
from mailtaskagent.policy import validate_status_transition
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.task_context_agent import TaskContextAgent, build_task_context_agent


def load_mails(path: Path) -> list[MailInput]:
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    return [MailInput.model_validate(item) for item in payload]


def _duration_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)


def _needs_related_search(mail: MailInput, analysis: MailAnalysis) -> bool:
    reference_markers = ("지난", "관련 건", "기존", "앞서", "이전", "같이", "추가")
    text = f"{mail.subject} {mail.body}"
    return analysis.intent != MailIntent.NEW_TASK or any(marker in text for marker in reference_markers)


def _context_candidates(contexts: list[dict]) -> list[TaskCandidate]:
    return [TaskCandidate.model_validate(item["candidate"]) for item in contexts]


def _observed_context_summary(contexts: list[dict]) -> list[dict]:
    """Return safe, concise evidence of what the Agent observed after retrieval."""
    summaries = []
    for item in contexts:
        candidate = item["candidate"]
        histories = item.get("recent_histories", [])
        summaries.append(
            {
                "task_id": candidate["task_id"],
                "status": candidate["status"],
                "score": candidate.get("match_score", 0),
                "retrieval_reasons": item.get("retrieval_reasons", []),
                "recent_mail_count": len(item.get("recent_mails", [])),
                "recent_history_count": len(histories),
                "user_decision_count": sum(
                    1 for history in histories if history.get("user_decision")
                ),
            }
        )
    return summaries


def _validate_task_context_decision(
    decision: TaskContextDecision,
    contexts: list[dict],
) -> None:
    candidate_ids = {item["candidate"]["task_id"] for item in contexts}
    if decision.selected_task_id and decision.selected_task_id not in candidate_ids:
        raise ValueError("Task Context Agent selected a Task outside retrieved candidates")
    if decision.relation == TaskRelation.SAME_TASK and not decision.selected_task_id:
        raise ValueError("SAME_TASK requires a retrieved Task ID")
    if decision.relation == TaskRelation.NEW_TASK and decision.selected_task_id:
        raise ValueError("NEW_TASK must not select an existing Task ID")


def _needs_rag_retry(decision: TaskContextDecision, threshold: float) -> bool:
    return decision.relation == TaskRelation.AMBIGUOUS or decision.confidence < threshold


def _validate_proposal(proposal: ActionProposal, candidates: list[TaskCandidate]) -> None:
    candidate_ids = {candidate.task_id for candidate in candidates}
    candidates_by_id = {candidate.task_id: candidate for candidate in candidates}
    if proposal.action == AgentAction.CREATE_TASK:
        required = {"conversation_id", "title", "description", "status"}
        missing = required - set(proposal.task_payload)
        if missing:
            raise ValueError(f"CREATE_TASK payload missing: {sorted(missing)}")
    elif proposal.action in {AgentAction.UPDATE_TASK, AgentAction.SET_WAITING}:
        if not proposal.target_task_id or proposal.target_task_id not in candidate_ids:
            raise ValueError(f"{proposal.action.value} target must be a matched Task")
        if not proposal.changes:
            raise ValueError(f"{proposal.action.value} requires changes")
        if proposal.action == AgentAction.SET_WAITING and (
            proposal.changes.get("status") != "WAITING_REPLY"
            or not proposal.changes.get("waiting_since")
        ):
            raise ValueError("SET_WAITING requires WAITING_REPLY status and waiting_since")
        if "status" in proposal.changes:
            validate_status_transition(
                candidates_by_id[proposal.target_task_id].status,
                proposal.changes["status"],
            )
    elif proposal.action == AgentAction.LINK_TO_TASK:
        if not proposal.target_task_id or proposal.target_task_id not in candidate_ids:
            raise ValueError("LINK_TO_TASK target must be a matched Task")
    elif proposal.action == AgentAction.MARK_COMPLETED:
        if not proposal.target_task_id or proposal.target_task_id not in candidate_ids:
            raise ValueError("MARK_COMPLETED target must be a matched Task")
        if proposal.changes.get("status") != "COMPLETED":
            raise ValueError("MARK_COMPLETED must propose COMPLETED status")
        if not proposal.needs_user_confirmation:
            raise ValueError("MARK_COMPLETED requires user confirmation")
        validate_status_transition(
            candidates_by_id[proposal.target_task_id].status,
            proposal.changes["status"],
        )
    elif proposal.action == AgentAction.ASK_USER:
        if not proposal.needs_user_confirmation:
            raise ValueError("ASK_USER must require user confirmation")
        if proposal.changes.get("status") == "CANCELLED" and (
            not proposal.target_task_id or proposal.target_task_id not in candidate_ids
        ):
            raise ValueError("Cancellation review target must be a matched Task")
        if proposal.changes.get("status") == "CANCELLED":
            validate_status_transition(
                candidates_by_id[proposal.target_task_id].status,
                proposal.changes["status"],
            )


class MailTaskWorkflow:
    def __init__(
        self,
        settings: Settings,
        storage: SQLiteStorage,
        analyzer: MailAnalyzer,
        task_context_agent: TaskContextAgent | None = None,
    ):
        if (
            settings.task_context_rag_enabled
            and settings.task_context_rag_max_retries != 1
        ):
            raise ValueError("TASK_CONTEXT_RAG_MAX_RETRIES must be exactly 1")
        self.settings = settings
        self.storage = storage
        self.analyzer = analyzer
        self.task_context_agent = (
            task_context_agent or build_task_context_agent(settings)
            if settings.task_context_rag_enabled
            else None
        )
        self.storage.initialize()

    def _event(self, case_id: str, mail_id: str, step: str, status: str, message: str, **kwargs) -> None:
        self.storage.append_event(
            case_id=case_id,
            mail_id=mail_id,
            step=step,
            status=status,
            message=message,
            **kwargs,
        )

    def process(self, mail: MailInput) -> WorkflowResult:
        case_id = f"CASE-{uuid4().hex[:10].upper()}"
        self._event(
            case_id,
            mail.mail_id,
            "MAIL_INPUT",
            "SUCCESS",
            "합성 Mail 입력 수신",
            details={
                "conversation_id": mail.conversation_id,
                "direction": mail.direction.value,
                "subject": mail.subject,
                "occurred_at": mail.occurred_at.isoformat(),
            },
        )
        self._event(
            case_id,
            mail.mail_id,
            "SCHEMA_VALIDATION",
            "SUCCESS",
            "MailInput Pydantic Schema 검증 통과",
        )

        try:
            duplicate_started = perf_counter()
            if self.storage.is_processed(mail.mail_id):
                previous = self.storage.get_processing_result(mail.mail_id) or {}
                self._event(
                    case_id,
                    mail.mail_id,
                    "DUPLICATE_CHECK",
                    "DUPLICATE",
                    "이미 처리된 mail_id: 기존 결과 반환, LLM/DB 재실행 없음",
                    level="WARNING",
                    duration_ms=_duration_ms(duplicate_started),
                )
                return WorkflowResult(
                    case_id=previous.get("case_id", case_id),
                    mail=mail,
                    analysis=MailAnalysis.model_validate(previous["analysis"]),
                    proposal=ActionProposal.model_validate(previous["proposal"]),
                    thread_history=previous.get("thread_history", []),
                    candidate_tasks=[
                        TaskCandidate.model_validate(item)
                        for item in previous.get("candidate_tasks", [])
                    ],
                    current_task_context=previous.get("current_task_context"),
                    retrieval_query=previous.get("retrieval_query"),
                    retrieved_task_contexts=previous.get("retrieved_task_contexts", []),
                    task_context_decision=(
                        TaskContextDecision.model_validate(previous["task_context_decision"])
                        if previous.get("task_context_decision")
                        else None
                    ),
                    guard_result=(
                        GuardedActionResult.model_validate(previous["guard_result"])
                        if previous.get("guard_result")
                        else None
                    ),
                    rag_retry_count=previous.get("rag_retry_count", 0),
                    match_route=previous.get("match_route", "LEGACY"),
                    validation_result=previous.get("validation_result", {}),
                    task=previous.get("task"),
                    before=previous.get("before"),
                    after=previous.get("after"),
                    review_result=previous.get("review_result"),
                    duplicate=True,
                )
            self._event(
                case_id,
                mail.mail_id,
                "DUPLICATE_CHECK",
                "SUCCESS",
                "신규 mail_id 확인",
                duration_ms=_duration_ms(duplicate_started),
            )

            analysis_started = perf_counter()
            self._event(
                case_id,
                mail.mail_id,
                "M-01 LLM_ANALYSIS",
                "STARTED",
                f"Mail Analysis 시작 ({self.settings.llm_mode})",
                details={
                    "mode": self.settings.llm_mode,
                    "model": self.settings.model,
                    "endpoint": self.settings.api_url,
                },
            )
            try:
                analysis = self.analyzer.analyze(mail)
            except Exception as exc:
                self._event(
                    case_id,
                    mail.mail_id,
                    "M-01 LLM_ANALYSIS",
                    "FAILED",
                    f"회사 LLM API 호출 또는 구조화 분석 실패: {type(exc).__name__}: {exc}",
                    level="ERROR",
                    details={"error_type": type(exc).__name__, "task_db_changed": False},
                    duration_ms=_duration_ms(analysis_started),
                )
                raise
            analysis_source = getattr(
                self.analyzer,
                "last_analysis_source",
                self.settings.llm_mode,
            )
            self._event(
                case_id,
                mail.mail_id,
                "M-01 LLM_ANALYSIS",
                "SUCCESS",
                (
                    "사용자 Mail 제외 Rule 적용 완료, LLM 호출 생략"
                    if analysis_source == "USER_FILTER_RULE"
                    else (
                        "회사 LLM API 호출 및 구조화 분석 완료"
                        if not self.settings.use_mock
                        else "Mock 구조화 분석 완료"
                    )
                ),
                details={
                    "analysis_source": analysis_source,
                    "is_task_request": analysis.is_task_request,
                    "intent": analysis.intent.value,
                    "task_title": analysis.task_title,
                    "request_summary": analysis.request_summary,
                    "requester": analysis.requester,
                    "due_date": analysis.due_date,
                    "reply_required": analysis.reply_required,
                    "confidence": analysis.confidence,
                },
                duration_ms=_duration_ms(analysis_started),
            )

            match_started = perf_counter()
            self._event(
                case_id,
                mail.mail_id,
                "M-02 TASK_MATCHING",
                "STARTED",
                "기존 활성 Task 후보 검색 시작",
            )
            thread_history = self.storage.list_thread_mails(mail.conversation_id)
            query_text = " ".join(
                filter(
                    None,
                    [
                        mail.subject,
                        analysis.task_title,
                        analysis.request_summary,
                        analysis.requester,
                    ],
                )
            )
            retrieval_query: str | None = None
            retrieved_task_contexts: list[dict] = []
            task_context_decision: TaskContextDecision | None = None
            guard_result: GuardedActionResult | None = None
            rag_retry_count = 0
            rag_fallback_reason: str | None = None
            match_route = "LEGACY"
            exact_candidates = self.storage.search_candidate_tasks(
                mail.conversation_id,
                "",
                include_related=False,
            )

            if self.task_context_agent is not None and len(exact_candidates) == 1:
                candidates = exact_candidates
                current_task_context = self.storage.get_task_context(candidates[0].task_id)
                match_route = "THREAD_EXACT"
                self._event(
                    case_id,
                    mail.mail_id,
                    "M-02 CONTEXT_ROUTE",
                    "SUCCESS",
                    "동일 conversation_id의 단일 활성 Task 확정, RAG 호출 생략",
                    details={
                        "route": match_route,
                        "candidate_task_ids": [candidates[0].task_id],
                        "rag_called": False,
                    },
                )
            elif self.task_context_agent is not None and analysis.is_task_request and (
                exact_candidates or _needs_related_search(mail, analysis)
            ):
                match_route = "STRUCTURED_RAG"
                retrieval_query = query_text
                retrieval_started = perf_counter()
                retrieved_task_contexts = self.storage.retrieve_task_contexts(
                    retrieval_query,
                    analysis.requester,
                    top_k=self.settings.task_context_rag_top_k,
                    conversation_id=mail.conversation_id,
                )
                candidates = _context_candidates(retrieved_task_contexts)
                self._event(
                    case_id,
                    mail.mail_id,
                    "M-02 RAG_RETRIEVAL",
                    "SUCCESS",
                    f"SQLite Task Context top-k 검색 완료: {len(candidates)}개",
                    details={
                        "route": match_route,
                        "query": retrieval_query,
                        "candidate_task_ids": [item.task_id for item in candidates],
                        "retrieval_results": [
                            {
                                "task_id": item.task_id,
                                "score": item.match_score,
                                "reason": item.match_reason,
                            }
                            for item in candidates
                        ],
                        "recent_mail_limit": 3,
                        "history_limit": 5,
                    },
                    duration_ms=_duration_ms(retrieval_started),
                )
                self._event(
                    case_id,
                    mail.mail_id,
                    "M-02 CONTEXT_OBSERVATION",
                    "SUCCESS",
                    "검색 후보의 현재 상태와 제한된 최근 Mail·History·사용자 결정을 관찰",
                    details={
                        "retry_count": 0,
                        "observed_contexts": _observed_context_summary(
                            retrieved_task_contexts
                        ),
                    },
                )
                try:
                    decision_started = perf_counter()
                    task_context_decision = self.task_context_agent.judge(
                        mail,
                        analysis,
                        retrieved_task_contexts,
                        retry_count=0,
                    )
                    _validate_task_context_decision(
                        task_context_decision, retrieved_task_contexts
                    )
                    self._event(
                        case_id,
                        mail.mail_id,
                        "M-03 RAG_DECISION",
                        "SUCCESS",
                        "Task Context Agent가 검색 결과를 관찰하고 관계를 판단",
                        details={
                            **task_context_decision.model_dump(mode="json"),
                            "retry_count": 0,
                            "candidate_task_ids": [item.task_id for item in candidates],
                        },
                        duration_ms=_duration_ms(decision_started),
                    )

                    if _needs_rag_retry(
                        task_context_decision,
                        self.settings.task_context_rag_confidence_threshold,
                    ) and task_context_decision.rewritten_query:
                        rag_retry_count = 1
                        retrieval_query = task_context_decision.rewritten_query
                        self._event(
                            case_id,
                            mail.mail_id,
                            "M-03 QUERY_REWRITE",
                            "SUCCESS",
                            "저신뢰·모호성으로 검색 Query 재작성, 제한 재시도 1회",
                            details={
                                "query": retrieval_query,
                                "retry_count": rag_retry_count,
                                "decision_reason": task_context_decision.reason,
                            },
                        )
                        retry_started = perf_counter()
                        retrieved_task_contexts = self.storage.retrieve_task_contexts(
                            retrieval_query,
                            analysis.requester,
                            top_k=self.settings.task_context_rag_top_k,
                            conversation_id=mail.conversation_id,
                        )
                        candidates = _context_candidates(retrieved_task_contexts)
                        self._event(
                            case_id,
                            mail.mail_id,
                            "M-02 RAG_RETRIEVAL_RETRY",
                            "SUCCESS",
                            f"재작성 Query로 Task Context 재검색 완료: {len(candidates)}개",
                            details={
                                "query": retrieval_query,
                                "retry_count": rag_retry_count,
                                "candidate_task_ids": [item.task_id for item in candidates],
                                "retrieval_results": [
                                    {
                                        "task_id": item.task_id,
                                        "score": item.match_score,
                                        "reason": item.match_reason,
                                    }
                                    for item in candidates
                                ],
                            },
                            duration_ms=_duration_ms(retry_started),
                        )
                        self._event(
                            case_id,
                            mail.mail_id,
                            "M-02 CONTEXT_REOBSERVATION",
                            "SUCCESS",
                            "재검색 후보의 상태와 최근 Context를 다시 관찰",
                            details={
                                "retry_count": rag_retry_count,
                                "observed_contexts": _observed_context_summary(
                                    retrieved_task_contexts
                                ),
                            },
                        )
                        redecision_started = perf_counter()
                        task_context_decision = self.task_context_agent.judge(
                            mail,
                            analysis,
                            retrieved_task_contexts,
                            retry_count=rag_retry_count,
                        )
                        _validate_task_context_decision(
                            task_context_decision, retrieved_task_contexts
                        )
                        self._event(
                            case_id,
                            mail.mail_id,
                            "M-03 RAG_REDECISION",
                            "SUCCESS",
                            "재검색 결과를 관찰하고 Task 관계를 최종 재판단",
                            details={
                                **task_context_decision.model_dump(mode="json"),
                                "retry_count": rag_retry_count,
                                "candidate_task_ids": [item.task_id for item in candidates],
                            },
                            duration_ms=_duration_ms(redecision_started),
                        )

                    if _needs_rag_retry(
                        task_context_decision,
                        self.settings.task_context_rag_confidence_threshold,
                    ):
                        rag_fallback_reason = (
                            (
                                "Task Context 재판단 후에도 "
                                if rag_retry_count
                                else "Task Context 판단 결과 "
                            )
                            + "관계가 모호하거나 신뢰도가 기준 미만: "
                            f"{task_context_decision.reason}"
                        )
                    elif task_context_decision.relation == TaskRelation.SAME_TASK:
                        selected = task_context_decision.selected_task_id
                        candidates = [item for item in candidates if item.task_id == selected]
                    elif task_context_decision.relation == TaskRelation.NEW_TASK:
                        candidates = []
                except Exception as exc:
                    rag_fallback_reason = (
                        "Task Context RAG/Agent 검증 실패로 자동 연결 중단: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    task_context_decision = None
                    self._event(
                        case_id,
                        mail.mail_id,
                        "RAG_FALLBACK",
                        "FAILED",
                        rag_fallback_reason,
                        level="ERROR",
                        details={
                            "error_type": type(exc).__name__,
                            "candidate_task_ids": [item.task_id for item in candidates],
                            "task_db_changed": False,
                        },
                    )

                current_task_context = (
                    self.storage.get_task_context(candidates[0].task_id)
                    if len(candidates) == 1
                    else None
                )
            else:
                candidates = self.storage.search_candidate_tasks(
                    mail.conversation_id,
                    query_text,
                    include_related=_needs_related_search(mail, analysis),
                )
                current_task_context = (
                    self.storage.get_task_context(candidates[0].task_id)
                    if len(candidates) == 1
                    else None
                )
            self._event(
                case_id,
                mail.mail_id,
                "M-02 TASK_MATCHING",
                "SUCCESS",
                f"활성 Task 후보 {len(candidates)}개 검색",
                details={
                    "candidate_count": len(candidates),
                    "thread_mail_count": len(thread_history),
                    "selected_task_history_count": len(
                        (current_task_context or {}).get("recent_histories", [])
                    ),
                    "match_route": match_route,
                    "rag_retry_count": rag_retry_count,
                    "candidates": [
                        {
                            "task_id": item.task_id,
                            "title": item.title,
                            "status": item.status.value,
                            "match_score": item.match_score,
                            "match_reason": item.match_reason,
                        }
                        for item in candidates
                    ],
                },
                duration_ms=_duration_ms(match_started),
            )

            decision_started = perf_counter()
            if rag_fallback_reason:
                proposal = ActionProposal(
                    action=AgentAction.ASK_USER,
                    reason=rag_fallback_reason,
                    confidence=(
                        task_context_decision.confidence
                        if task_context_decision
                        else 0.0
                    ),
                    needs_user_confirmation=True,
                )
                if task_context_decision is not None:
                    self._event(
                        case_id,
                        mail.mail_id,
                        "M-03 AGENT_ACTION_PROPOSAL",
                        "SUCCESS",
                        (
                            "Task Context Agent의 저신뢰·모호한 Action 제안을 "
                            "Safety Guard로 전달"
                        ),
                        details={
                            "route": match_route,
                            "relation": task_context_decision.relation.value,
                            "action": task_context_decision.recommended_action.value,
                            "selected_task_id": task_context_decision.selected_task_id,
                            "confidence": task_context_decision.confidence,
                            "reason": task_context_decision.reason,
                        },
                    )
                    guard_result = GuardedActionResult(
                        verdict=GuardVerdict.ESCALATED,
                        agent_action=task_context_decision.recommended_action,
                        final_proposal=proposal,
                        reason=rag_fallback_reason,
                    )
                    self._event(
                        case_id,
                        mail.mail_id,
                        "M-03 PYTHON_GUARD",
                        "WAITING",
                        "Task Context 신뢰도 정책에 따라 사용자 확인 단계로 이관",
                        level="WARNING",
                        details={
                            "route": match_route,
                            "verdict": guard_result.verdict.value,
                            "agent_action": guard_result.agent_action.value,
                            "action": proposal.action.value,
                            "target_task_id": proposal.target_task_id,
                            "reason": guard_result.reason,
                            "needs_user_confirmation": True,
                        },
                    )
                self._event(
                    case_id,
                    mail.mail_id,
                    "ASK_USER",
                    "WAITING",
                    "RAG/ReAct가 안전하게 확정하지 못해 사용자에게 제어권 이관",
                    level="WARNING",
                    details={
                        "reason": rag_fallback_reason,
                        "retry_count": rag_retry_count,
                        "task_db_changed": False,
                    },
                )
            elif match_route == "STRUCTURED_RAG" and task_context_decision is not None:
                self._event(
                    case_id,
                    mail.mail_id,
                    "M-03 AGENT_ACTION_PROPOSAL",
                    "SUCCESS",
                    f"Task Context Agent Action 제안: {task_context_decision.recommended_action.value}",
                    details={
                        "route": match_route,
                        "relation": task_context_decision.relation.value,
                        "action": task_context_decision.recommended_action.value,
                        "selected_task_id": task_context_decision.selected_task_id,
                        "confidence": task_context_decision.confidence,
                        "reason": task_context_decision.reason,
                    },
                )
                guard_result = build_guarded_agent_proposal(
                    mail,
                    analysis,
                    candidates,
                    task_context_decision,
                    self.settings,
                )
                proposal = guard_result.final_proposal
                self._event(
                    case_id,
                    mail.mail_id,
                    "M-03 PYTHON_GUARD",
                    "SUCCESS" if guard_result.verdict == GuardVerdict.ACCEPTED else "WAITING",
                    (
                        "Python Safety Guard가 Agent Proposal 실행 승인"
                        if guard_result.verdict == GuardVerdict.ACCEPTED
                        else "Python Safety Guard가 Agent Proposal을 사용자 확인 단계로 이관"
                    ),
                    level=(
                        "INFO"
                        if guard_result.verdict == GuardVerdict.ACCEPTED
                        else "WARNING"
                    ),
                    details={
                        "route": match_route,
                        "verdict": guard_result.verdict.value,
                        "agent_action": guard_result.agent_action.value,
                        "action": proposal.action.value,
                        "target_task_id": proposal.target_task_id,
                        "materialized_fields": sorted(
                            set(proposal.task_payload) | set(proposal.changes)
                        ),
                        "reason": guard_result.reason,
                        "needs_user_confirmation": proposal.needs_user_confirmation,
                    },
                )
                if guard_result.verdict == GuardVerdict.ESCALATED:
                    self._event(
                        case_id,
                        mail.mail_id,
                        "ASK_USER",
                        "WAITING",
                        "Safety Guard 정책에 따라 사용자에게 최종 결정 이관",
                        level="WARNING",
                        details={
                            "agent_action": guard_result.agent_action.value,
                            "final_action": proposal.action.value,
                            "reason": guard_result.reason,
                            "task_db_changed": False,
                        },
                    )
            else:
                proposal = decide_action(mail, analysis, candidates, self.settings)
            self._event(
                case_id,
                mail.mail_id,
                "M-03 ACTION_DECISION",
                "SUCCESS",
                f"Agent Action 결정: {proposal.action.value}",
                details={
                    "action": proposal.action.value,
                    "target_task_id": proposal.target_task_id,
                    "reason": proposal.reason,
                    "confidence": proposal.confidence,
                    "needs_user_confirmation": proposal.needs_user_confirmation,
                    "match_route": match_route,
                    "llm_recommended_action": (
                        task_context_decision.recommended_action.value
                        if task_context_decision
                        else None
                    ),
                    "python_guard_override": bool(
                        guard_result
                        and guard_result.agent_action != proposal.action
                    ),
                    "guard_verdict": (
                        guard_result.verdict.value if guard_result else None
                    ),
                },
                duration_ms=_duration_ms(decision_started),
            )

            validation_started = perf_counter()
            try:
                _validate_proposal(proposal, candidates)
            except Exception as exc:
                self._event(
                    case_id,
                    mail.mail_id,
                    "ACTION_VALIDATION",
                    "FAILED",
                    f"Action 실행 정책 검증 실패: {type(exc).__name__}: {exc}",
                    level="ERROR",
                    duration_ms=_duration_ms(validation_started),
                )
                raise
            self._event(
                case_id,
                mail.mail_id,
                "ACTION_VALIDATION",
                "SUCCESS",
                "Pydantic 및 Action 실행 정책 검증 통과",
                duration_ms=_duration_ms(validation_started),
            )
            validation_result = {
                "passed": True,
                "schema": "Pydantic",
                "policy": "Action Enum, Task ID, payload and status transition",
            }

            db_started = perf_counter()
            self._event(
                case_id,
                mail.mail_id,
                "M-04 DB_TRANSACTION",
                "STARTED",
                "Task/Link/History Transaction 시작",
            )
            try:
                task, before, after = self.storage.apply(
                    case_id,
                    mail,
                    analysis,
                    proposal,
                    candidates,
                    thread_history=thread_history,
                    current_task_context=current_task_context,
                    validation_result=validation_result,
                    retrieval_query=retrieval_query,
                    retrieved_task_contexts=retrieved_task_contexts,
                    task_context_decision=task_context_decision,
                    guard_result=guard_result,
                    rag_retry_count=rag_retry_count,
                    match_route=match_route,
                )
            except Exception as exc:
                self._event(
                    case_id,
                    mail.mail_id,
                    "M-04 DB_TRANSACTION",
                    "FAILED",
                    f"DB Transaction Rollback: {type(exc).__name__}: {exc}",
                    level="ERROR",
                    details={"rollback": True, "task_db_changed": False},
                    duration_ms=_duration_ms(db_started),
                )
                raise
            self._event(
                case_id,
                mail.mail_id,
                "M-04 DB_TRANSACTION",
                "SUCCESS",
                "DB 반영 및 History 저장 완료",
                details={
                    "task_changed": proposal.action
                    in {
                        AgentAction.CREATE_TASK,
                        AgentAction.UPDATE_TASK,
                        AgentAction.SET_WAITING,
                    },
                    "task_id": task.get("task_id") if task else proposal.target_task_id,
                    "history_saved": True,
                    "waiting_for_user": proposal.needs_user_confirmation,
                },
                duration_ms=_duration_ms(db_started),
            )
            observed_task_id = (
                task.get("task_id") if task else proposal.target_task_id
            )
            observed_task = (
                self.storage.get_task(observed_task_id) if observed_task_id else None
            )
            self._event(
                case_id,
                mail.mail_id,
                "M-04 EXECUTION_OBSERVATION",
                "SUCCESS",
                "Action 실행 후 실제 저장 상태 관찰 완료",
                details={
                    "action": proposal.action.value,
                    "task_id": observed_task_id,
                    "observed_status": (
                        observed_task.get("status") if observed_task else None
                    ),
                    "expected_after_matches": (
                        not after or observed_task == after
                    ),
                    "waiting_for_user": proposal.needs_user_confirmation,
                },
            )
            self._event(
                case_id,
                mail.mail_id,
                "PROCESS_COMPLETED",
                "SUCCESS",
                "Mail 처리 완료"
                if not proposal.needs_user_confirmation
                else "Agent 제안 저장 완료, 사용자 최종 결정 대기",
            )
            self._event(
                case_id,
                mail.mail_id,
                "FINAL_OUTPUT",
                "SUCCESS",
                "Agent Workflow 최종 결과 확정",
                details={
                    "action": proposal.action.value,
                    "task_id": observed_task_id,
                    "match_route": match_route,
                    "rag_retry_count": rag_retry_count,
                    "user_review_required": proposal.needs_user_confirmation,
                },
            )
            return WorkflowResult(
                case_id=case_id,
                mail=mail,
                analysis=analysis,
                proposal=proposal,
                thread_history=thread_history,
                candidate_tasks=candidates,
                current_task_context=current_task_context,
                retrieval_query=retrieval_query,
                retrieved_task_contexts=retrieved_task_contexts,
                task_context_decision=task_context_decision,
                guard_result=guard_result,
                rag_retry_count=rag_retry_count,
                match_route=match_route,
                validation_result=validation_result,
                task=task,
                before=before,
                after=after,
            )
        except Exception as exc:
            self._event(
                case_id,
                mail.mail_id,
                "PROCESS_FAILED",
                "FAILED",
                f"처리 중단: {type(exc).__name__}: {exc}",
                level="ERROR",
                details={"error_type": type(exc).__name__, "task_db_changed": False},
            )
            raise

    def resolve_review(
        self,
        *,
        mail: MailInput,
        decision: ReviewDecision,
        target_task_id: str | None = None,
        new_task_title: str | None = None,
        approved_changes: dict | None = None,
    ) -> dict:
        case_id = f"REVIEW-{uuid4().hex[:10].upper()}"
        started = perf_counter()
        self._event(
            case_id,
            mail.mail_id,
            "M-05 USER_REVIEW",
            "STARTED",
            "ASK_USER 사용자 확인 시작",
            details={"decision": decision.value, "target_task_id": target_task_id},
        )
        try:
            result = self.storage.resolve_review(
                mail=mail,
                decision=decision,
                target_task_id=target_task_id,
                new_task_title=new_task_title,
                approved_changes=approved_changes,
            )
            self._event(
                case_id,
                mail.mail_id,
                "M-05 USER_REVIEW",
                "SUCCESS",
                f"사용자 최종 결정 반영: {result['final_action']}",
                details={
                    "decision": result["decision"],
                    "final_action": result["final_action"],
                    "task_id": result["task_id"],
                    "history_saved": True,
                },
                duration_ms=_duration_ms(started),
            )
            return result
        except Exception as exc:
            self._event(
                case_id,
                mail.mail_id,
                "M-05 USER_REVIEW",
                "FAILED",
                f"사용자 결정 반영 실패: {type(exc).__name__}: {exc}",
                level="ERROR",
                duration_ms=_duration_ms(started),
            )
            raise
