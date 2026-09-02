from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from mailtaskagent.config import Settings
from mailtaskagent.decision import build_guarded_agent_proposal
from mailtaskagent.models import (
    AgentAction,
    GuardVerdict,
    MailAnalysis,
    MailDirection,
    MailInput,
    MailIntent,
    TaskCandidate,
    TaskContextDecision,
    TaskRelation,
    TaskStatus,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=tmp_path / "guard.db",
        confidence_threshold=0.75,
        task_context_rag_enabled=True,
    )


def _mail(*, direction: MailDirection = MailDirection.INBOUND, body: str = "변경해 주세요") -> MailInput:
    timestamp = datetime(2026, 9, 2, 9, tzinfo=UTC)
    return MailInput(
        mail_id="GUARD-MAIL",
        conversation_id="THREAD-GUARD",
        direction=direction,
        sender="owner@example.test",
        recipients=["worker@example.test"],
        received_at=timestamp if direction == MailDirection.INBOUND else None,
        sent_at=timestamp if direction == MailDirection.OUTBOUND else None,
        subject="기존 업무 후속",
        body=body,
    )


def _analysis(
    intent: MailIntent,
    *,
    title: str | None = "접근통제 점검",
    summary: str | None = "접근통제 점검 결과를 갱신한다.",
    due_date: date | None = None,
) -> MailAnalysis:
    return MailAnalysis(
        is_task_request=intent != MailIntent.NON_TASK,
        intent=intent,
        task_title=title,
        request_summary=summary,
        requester="owner@example.test",
        due_date=due_date,
        reply_required=True,
        reason="합성 Agent Action Guard 검증",
        confidence=0.94,
    )


def _candidate(*, status: TaskStatus = TaskStatus.TODO) -> TaskCandidate:
    return TaskCandidate(
        task_id="TASK-001",
        conversation_id="THREAD-OLD",
        title="접근통제 점검",
        requester="owner@example.test",
        description="기존 점검 결과",
        due_date=date(2026, 9, 15),
        reply_required=False,
        status=status,
        match_score=0.88,
        match_reason="최근 Mail과 History 일치",
    )


def _decision(
    action: AgentAction,
    *,
    relation: TaskRelation = TaskRelation.SAME_TASK,
    selected_task_id: str | None = "TASK-001",
) -> TaskContextDecision:
    return TaskContextDecision(
        relation=relation,
        selected_task_id=selected_task_id,
        recommended_action=action,
        confidence=0.91,
        reason="최근 Context를 근거로 선택한 Agent Action",
    )


def test_agent_create_task_proposal_is_materialized(tmp_path: Path) -> None:
    result = build_guarded_agent_proposal(
        _mail(),
        _analysis(MailIntent.NEW_TASK),
        [],
        _decision(
            AgentAction.CREATE_TASK,
            relation=TaskRelation.NEW_TASK,
            selected_task_id=None,
        ),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ACCEPTED
    assert result.final_proposal.action == AgentAction.CREATE_TASK
    assert result.final_proposal.task_payload["status"] == TaskStatus.TODO.value


def test_agent_update_task_proposal_is_materialized(tmp_path: Path) -> None:
    candidate = _candidate()
    result = build_guarded_agent_proposal(
        _mail(),
        _analysis(MailIntent.TASK_UPDATE),
        [candidate],
        _decision(AgentAction.UPDATE_TASK),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ACCEPTED
    assert result.final_proposal.action == AgentAction.UPDATE_TASK
    assert result.final_proposal.target_task_id == candidate.task_id
    assert result.final_proposal.changes["description"] == "접근통제 점검 결과를 갱신한다."


def test_agent_can_select_one_task_from_ranked_candidate_pool(tmp_path: Path) -> None:
    selected = _candidate()
    other = _candidate().model_copy(
        update={
            "task_id": "TASK-002",
            "title": "다른 업무",
            "description": "별도 후보",
            "match_score": 0.52,
        }
    )
    result = build_guarded_agent_proposal(
        _mail(),
        _analysis(MailIntent.TASK_UPDATE),
        [other, selected],
        _decision(AgentAction.UPDATE_TASK, selected_task_id=selected.task_id),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ACCEPTED
    assert result.final_proposal.target_task_id == selected.task_id


def test_agent_link_proposal_is_accepted_when_no_field_changes(tmp_path: Path) -> None:
    candidate = _candidate()
    result = build_guarded_agent_proposal(
        _mail(body="기존 내용 그대로 진행해 주세요"),
        _analysis(MailIntent.TASK_UPDATE, summary=candidate.description),
        [candidate],
        _decision(AgentAction.LINK_TO_TASK),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ACCEPTED
    assert result.final_proposal.action == AgentAction.LINK_TO_TASK
    assert result.final_proposal.changes == {}


def test_relation_and_action_mismatch_escalates(tmp_path: Path) -> None:
    result = build_guarded_agent_proposal(
        _mail(),
        _analysis(MailIntent.NEW_TASK),
        [],
        _decision(
            AgentAction.UPDATE_TASK,
            relation=TaskRelation.NEW_TASK,
            selected_task_id=None,
        ),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ESCALATED
    assert result.final_proposal.action == AgentAction.ASK_USER


def test_intent_and_action_mismatch_escalates(tmp_path: Path) -> None:
    result = build_guarded_agent_proposal(
        _mail(),
        _analysis(MailIntent.COMPLETION),
        [_candidate()],
        _decision(AgentAction.UPDATE_TASK),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ESCALATED
    assert result.final_proposal.action == AgentAction.ASK_USER


def test_candidate_mismatch_escalates(tmp_path: Path) -> None:
    result = build_guarded_agent_proposal(
        _mail(),
        _analysis(MailIntent.TASK_UPDATE),
        [_candidate()],
        _decision(AgentAction.UPDATE_TASK, selected_task_id="TASK-OUTSIDE"),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ESCALATED
    assert result.final_proposal.action == AgentAction.ASK_USER


def test_missing_create_payload_escalates(tmp_path: Path) -> None:
    result = build_guarded_agent_proposal(
        _mail(),
        _analysis(MailIntent.NEW_TASK, title=None, summary=None),
        [],
        _decision(
            AgentAction.CREATE_TASK,
            relation=TaskRelation.NEW_TASK,
            selected_task_id=None,
        ),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ESCALATED
    assert result.final_proposal.action == AgentAction.ASK_USER


def test_due_date_reduction_preserves_review_gate(tmp_path: Path) -> None:
    result = build_guarded_agent_proposal(
        _mail(),
        _analysis(MailIntent.DUE_DATE_CHANGE, due_date=date(2026, 9, 10)),
        [_candidate()],
        _decision(AgentAction.UPDATE_TASK),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ESCALATED
    assert result.final_proposal.action == AgentAction.ASK_USER
    assert result.final_proposal.changes == {"due_date": "2026-09-10"}


def test_completion_preserves_user_approval_gate(tmp_path: Path) -> None:
    result = build_guarded_agent_proposal(
        _mail(),
        _analysis(MailIntent.COMPLETION),
        [_candidate()],
        _decision(AgentAction.MARK_COMPLETED),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ESCALATED
    assert result.final_proposal.action == AgentAction.MARK_COMPLETED
    assert result.final_proposal.needs_user_confirmation is True


def test_inbound_set_waiting_escalates(tmp_path: Path) -> None:
    result = build_guarded_agent_proposal(
        _mail(direction=MailDirection.INBOUND),
        _analysis(MailIntent.WAITING),
        [_candidate()],
        _decision(AgentAction.SET_WAITING),
        _settings(tmp_path),
    )

    assert result.verdict == GuardVerdict.ESCALATED
    assert result.final_proposal.action == AgentAction.ASK_USER
