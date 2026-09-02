from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from mailtaskagent.config import Settings
from mailtaskagent.models import (
    AgentAction,
    MailAnalysis,
    MailDirection,
    MailInput,
    MailIntent,
    TaskContextDecision,
    TaskRelation,
)
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow


class _StaticAnalyzer:
    def __init__(self, analysis: MailAnalysis):
        self.analysis = analysis

    def analyze(self, mail: MailInput) -> MailAnalysis:
        return self.analysis


class _SelectFirstAgent:
    def __init__(self) -> None:
        self.calls = 0

    def judge(self, current_mail, mail_analysis, retrieved_task_contexts, *, retry_count):
        self.calls += 1
        return TaskContextDecision(
            relation=TaskRelation.SAME_TASK,
            selected_task_id=retrieved_task_contexts[0]["candidate"]["task_id"],
            recommended_action=AgentAction.UPDATE_TASK,
            confidence=0.93,
            reason="요청자와 최근 업무 이력이 같아 동일 업무로 판단",
        )


class _RewriteThenSelectAgent:
    def __init__(self) -> None:
        self.calls = 0

    def judge(self, current_mail, mail_analysis, retrieved_task_contexts, *, retry_count):
        self.calls += 1
        if retry_count == 0:
            return TaskContextDecision(
                relation=TaskRelation.AMBIGUOUS,
                recommended_action=AgentAction.ASK_USER,
                confidence=0.55,
                reason="첫 검색 표현만으로 동일 업무를 확정하기 어려움",
                rewritten_query="접근통제 장애 영향도 점검 결과 공유",
            )
        return TaskContextDecision(
            relation=TaskRelation.SAME_TASK,
            selected_task_id=retrieved_task_contexts[0]["candidate"]["task_id"],
            recommended_action=AgentAction.UPDATE_TASK,
            confidence=0.91,
            reason="재작성 Query의 검색 결과와 최근 History가 일치함",
        )


class _AlwaysAmbiguousAgent:
    def judge(self, current_mail, mail_analysis, retrieved_task_contexts, *, retry_count):
        return TaskContextDecision(
            relation=TaskRelation.AMBIGUOUS,
            recommended_action=AgentAction.ASK_USER,
            confidence=0.51,
            reason="복수 업무의 근거가 유사해 자동 연결할 수 없음",
            rewritten_query=("장애 관련 기존 업무" if retry_count == 0 else None),
        )


class _OutsideCandidateAgent:
    def judge(self, current_mail, mail_analysis, retrieved_task_contexts, *, retry_count):
        return TaskContextDecision(
            relation=TaskRelation.SAME_TASK,
            selected_task_id="TASK-NOT-RETRIEVED",
            recommended_action=AgentAction.UPDATE_TASK,
            confidence=0.99,
            reason="존재하지 않는 후보를 선택한 오류 응답",
        )


class _FailingAgent:
    def judge(self, current_mail, mail_analysis, retrieved_task_contexts, *, retry_count):
        raise ConnectionError("synthetic Task Context API failure")


@pytest.fixture
def base_settings(tmp_path: Path) -> Settings:
    return Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=tmp_path / "task-context-rag.db",
        confidence_threshold=0.75,
    )


def _mail(
    mail_id: str,
    conversation_id: str,
    *,
    subject: str,
    body: str,
    sender: str = "owner@example.test",
) -> MailInput:
    return MailInput(
        mail_id=mail_id,
        conversation_id=conversation_id,
        direction=MailDirection.INBOUND,
        sender=sender,
        recipients=["worker@example.test"],
        received_at=datetime(2026, 9, 2, 9, tzinfo=UTC),
        subject=subject,
        body=body,
    )


def _analysis(
    intent: MailIntent,
    *,
    title: str | None,
    summary: str,
    due_date: date | None = None,
    requester: str = "owner@example.test",
) -> MailAnalysis:
    return MailAnalysis(
        is_task_request=True,
        intent=intent,
        task_title=title,
        request_summary=summary,
        requester=requester,
        due_date=due_date,
        reply_required=True,
        reason="합성 Task Context RAG 검증 입력",
        confidence=0.94,
    )


def _seed_task(settings: Settings, storage: SQLiteStorage) -> dict:
    mail = _mail(
        "RAG-SEED",
        "THREAD-SEED",
        subject="접근통제 서버 장애 영향도 점검",
        body="장애 영향을 점검하고 결과를 공유해 주세요.",
    )
    result = MailTaskWorkflow(
        settings,
        storage,
        _StaticAnalyzer(
            _analysis(
                MailIntent.NEW_TASK,
                title="접근통제 서버 장애 영향도 점검",
                summary="접근통제 장애 영향을 점검하고 결과를 공유한다.",
                due_date=date(2026, 9, 10),
            )
        ),
    ).process(mail)
    assert result.task is not None
    return result.task


def _rag_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        task_context_rag_enabled=True,
        task_context_rag_top_k=5,
        task_context_rag_confidence_threshold=0.75,
        task_context_rag_max_retries=1,
    )


def test_rag_retry_limit_must_be_exactly_one(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    invalid_settings = replace(
        base_settings,
        task_context_rag_enabled=True,
        task_context_rag_max_retries=2,
    )

    with pytest.raises(ValueError, match="must be exactly 1"):
        MailTaskWorkflow(
            invalid_settings,
            storage,
            _StaticAnalyzer(
                _analysis(
                    MailIntent.NEW_TASK,
                    title="신규 업무",
                    summary="신규 업무를 수행한다.",
                )
            ),
            task_context_agent=_SelectFirstAgent(),
        )


def _followup_workflow(settings, storage, agent):
    analysis = _analysis(
        MailIntent.TASK_UPDATE,
        title=None,
        summary="장애 분석 자료를 반영해 최종 결과를 공유한다.",
    )
    return MailTaskWorkflow(
        _rag_settings(settings),
        storage,
        _StaticAnalyzer(analysis),
        task_context_agent=agent,
    )


def test_different_thread_and_wording_connects_same_task(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    seeded = _seed_task(base_settings, storage)
    workflow = _followup_workflow(base_settings, storage, _SelectFirstAgent())

    result = workflow.process(
        _mail(
            "RAG-01",
            "THREAD-OTHER",
            subject="서비스 영향 분석 후속",
            body="지난 분석 자료를 반영해서 최종본을 공유해 주세요.",
        )
    )

    assert result.match_route == "STRUCTURED_RAG"
    assert result.task_context_decision is not None
    assert result.task_context_decision.relation == TaskRelation.SAME_TASK
    assert result.proposal.action == AgentAction.UPDATE_TASK
    assert result.proposal.target_task_id == seeded["task_id"]
    assert len(storage.list_tasks()) == 1
    assert any(
        event["step"] == "M-03 RAG_DECISION"
        for event in storage.list_events("RAG-01")
    )


def test_exact_thread_bypasses_rag_agent(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    _seed_task(base_settings, storage)
    agent = _SelectFirstAgent()
    workflow = _followup_workflow(base_settings, storage, agent)

    result = workflow.process(
        _mail(
            "RAG-EXACT",
            "THREAD-SEED",
            subject="Re: 접근통제 서버 장애 영향도 점검",
            body="분석 자료를 추가 반영해 주세요.",
        )
    )

    assert result.match_route == "THREAD_EXACT"
    assert result.proposal.action == AgentAction.UPDATE_TASK
    assert agent.calls == 0
    route_event = next(
        event
        for event in storage.list_events("RAG-EXACT")
        if event["step"] == "M-02 CONTEXT_ROUTE"
    )
    assert '"rag_called": false' in route_event["details_json"]


def test_low_confidence_rewrites_query_once_then_connects(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    seeded = _seed_task(base_settings, storage)
    agent = _RewriteThenSelectAgent()
    workflow = _followup_workflow(base_settings, storage, agent)

    result = workflow.process(
        _mail("RAG-02", "THREAD-OTHER", subject="후속 공유", body="이 건 최종본 부탁드립니다.")
    )

    assert result.rag_retry_count == 1
    assert result.proposal.target_task_id == seeded["task_id"]
    assert result.proposal.action == AgentAction.UPDATE_TASK
    assert agent.calls == 2
    steps = {event["step"] for event in storage.list_events("RAG-02")}
    assert {
        "M-03 QUERY_REWRITE",
        "M-02 RAG_RETRIEVAL_RETRY",
        "M-03 RAG_REDECISION",
    } <= steps


def test_ambiguous_after_retry_fails_closed_to_ask_user(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    _seed_task(base_settings, storage)
    before = storage.list_tasks()
    workflow = _followup_workflow(base_settings, storage, _AlwaysAmbiguousAgent())

    result = workflow.process(
        _mail("RAG-03", "THREAD-OTHER", subject="지난 장애 건", body="관련 건도 확인해 주세요.")
    )

    assert result.rag_retry_count == 1
    assert result.proposal.action == AgentAction.ASK_USER
    assert storage.list_tasks() == before
    assert len(storage.list_pending_reviews()) == 1


@pytest.mark.parametrize("agent", [_OutsideCandidateAgent(), _FailingAgent()])
def test_invalid_or_failed_rag_does_not_change_tasks(
    base_settings: Settings, agent
) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    _seed_task(base_settings, storage)
    before = storage.list_tasks()
    workflow = _followup_workflow(base_settings, storage, agent)

    result = workflow.process(
        _mail("RAG-FAIL", "THREAD-OTHER", subject="관련 후속", body="기존 건을 변경해 주세요.")
    )

    assert result.proposal.action == AgentAction.ASK_USER
    assert storage.list_tasks() == before
    assert any(
        event["step"] == "RAG_FALLBACK"
        for event in storage.list_events("RAG-FAIL")
    )


def test_retrieval_contains_bounded_user_decision_memory(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    task = _seed_task(base_settings, storage)
    storage.update_task_by_user(
        task["task_id"],
        title=task["title"],
        description="사용자가 확정한 장애 영향 분석 범위",
        due_date=None,
        status=task["status"],
        reply_required=True,
    )

    contexts = storage.retrieve_task_contexts(
        "장애 영향 분석",
        "owner@example.test",
        top_k=5,
    )

    assert contexts[0]["candidate"]["task_id"] == task["task_id"]
    assert len(contexts[0]["recent_mails"]) <= 3
    assert len(contexts[0]["recent_histories"]) <= 5
    assert any(
        history["user_decision"] is not None
        for history in contexts[0]["recent_histories"]
    )


def test_execution_observation_is_recorded(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    _seed_task(base_settings, storage)
    workflow = _followup_workflow(base_settings, storage, _SelectFirstAgent())

    result = workflow.process(
        _mail("RAG-OBSERVE", "THREAD-OTHER", subject="장애 분석", body="결과에 내용을 추가해 주세요.")
    )

    observation = next(
        event
        for event in storage.list_events("RAG-OBSERVE")
        if event["step"] == "M-04 EXECUTION_OBSERVATION"
    )
    context_observation = next(
        event
        for event in storage.list_events("RAG-OBSERVE")
        if event["step"] == "M-02 CONTEXT_OBSERVATION"
    )
    assert result.proposal.action == AgentAction.UPDATE_TASK
    assert '"expected_after_matches": true' in observation["details_json"]
    assert '"recent_history_count"' in context_observation["details_json"]
    assert '"user_decision_count"' in context_observation["details_json"]


@pytest.mark.parametrize(
    ("intent", "due_date", "expected_action"),
    [
        (MailIntent.COMPLETION, None, AgentAction.MARK_COMPLETED),
        (MailIntent.CANCELLATION, None, AgentAction.ASK_USER),
        (MailIntent.DUE_DATE_CHANGE, date(2026, 9, 5), AgentAction.ASK_USER),
    ],
)
def test_rag_keeps_high_risk_user_approval_gates(
    base_settings: Settings,
    intent: MailIntent,
    due_date: date | None,
    expected_action: AgentAction,
) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    seeded = _seed_task(base_settings, storage)
    analysis = _analysis(
        intent,
        title=None,
        summary="기존 업무의 중요 상태 또는 기한을 변경한다.",
        due_date=due_date,
    )
    workflow = MailTaskWorkflow(
        _rag_settings(base_settings),
        storage,
        _StaticAnalyzer(analysis),
        task_context_agent=_SelectFirstAgent(),
    )

    result = workflow.process(
        _mail(
            f"RAG-GATE-{intent.value}",
            f"THREAD-GATE-{intent.value}",
            subject="기존 장애 점검 업무 변경",
            body="이전 업무 상태를 변경해 주세요.",
        )
    )

    assert result.proposal.action == expected_action
    assert result.proposal.needs_user_confirmation is True
    stored = storage.get_task(seeded["task_id"])
    assert stored is not None
    assert stored["status"] == "TODO"
    assert stored["due_date"] == "2026-09-10"


def test_agentic_rag_improves_no_token_cross_thread_case(
    base_settings: Settings,
) -> None:
    legacy_storage = SQLiteStorage(base_settings.database_path)
    _seed_task(base_settings, legacy_storage)
    rag_settings = replace(
        base_settings,
        database_path=base_settings.database_path.with_name("rag-compare.db"),
    )
    rag_storage = SQLiteStorage(rag_settings.database_path)
    seeded = _seed_task(rag_settings, rag_storage)
    mail = _mail(
        "RAG-COMPARE",
        "THREAD-PAM",
        subject="PAM 리포트 후속",
        body="리스크 리포트에 새로운 수치를 반영해 주세요.",
        sender="colleague@vendor.invalid",
    )
    analysis = _analysis(
        MailIntent.TASK_UPDATE,
        title=None,
        summary="PAM 서비스 리스크 리포트에 신규 수치를 반영한다.",
        requester="colleague@vendor.invalid",
    )

    legacy_result = MailTaskWorkflow(
        base_settings,
        legacy_storage,
        _StaticAnalyzer(analysis),
    ).process(mail)
    rag_result = MailTaskWorkflow(
        _rag_settings(rag_settings),
        rag_storage,
        _StaticAnalyzer(analysis),
        task_context_agent=_SelectFirstAgent(),
    ).process(mail)

    assert legacy_result.proposal.action == AgentAction.ASK_USER
    assert legacy_result.candidate_tasks == []
    assert rag_result.proposal.action == AgentAction.UPDATE_TASK
    assert rag_result.proposal.target_task_id == seeded["task_id"]
    assert rag_result.match_route == "STRUCTURED_RAG"
