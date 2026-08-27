from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from mailtaskagent.config import Settings
from mailtaskagent.decision import decide_action
from mailtaskagent.llm_client import MailAnalyzer
from mailtaskagent.models import (
    ActionProposal,
    AgentAction,
    MailAnalysis,
    MailInput,
    MailIntent,
    ReviewDecision,
    TaskCandidate,
    WorkflowResult,
)
from mailtaskagent.policy import validate_status_transition
from mailtaskagent.storage import SQLiteStorage


def load_mails(path: Path) -> list[MailInput]:
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    return [MailInput.model_validate(item) for item in payload]


def _duration_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)


def _needs_related_search(mail: MailInput, analysis: MailAnalysis) -> bool:
    reference_markers = ("지난", "관련 건", "기존", "앞서", "이전", "같이")
    text = f"{mail.subject} {mail.body}"
    return analysis.intent != MailIntent.NEW_TASK or any(marker in text for marker in reference_markers)


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
    def __init__(self, settings: Settings, storage: SQLiteStorage, analyzer: MailAnalyzer):
        self.settings = settings
        self.storage = storage
        self.analyzer = analyzer
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
            self._event(
                case_id,
                mail.mail_id,
                "M-01 LLM_ANALYSIS",
                "SUCCESS",
                "회사 LLM API 호출 및 구조화 분석 완료"
                if not self.settings.use_mock
                else "Mock 구조화 분석 완료",
                details={
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
            self._event(
                case_id,
                mail.mail_id,
                "PROCESS_COMPLETED",
                "SUCCESS",
                "Mail 처리 완료"
                if not proposal.needs_user_confirmation
                else "Agent 제안 저장 완료, 사용자 최종 결정 대기",
            )
            return WorkflowResult(
                case_id=case_id,
                mail=mail,
                analysis=analysis,
                proposal=proposal,
                thread_history=thread_history,
                candidate_tasks=candidates,
                current_task_context=current_task_context,
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
