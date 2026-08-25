import json
from datetime import date
from pathlib import Path

import pytest

from mailtaskagent.config import PROJECT_ROOT, Settings
from mailtaskagent.evaluation import load_saved_evaluation_report, run_scenario_evaluation
from mailtaskagent.llm_client import MockMailAnalyzer
from mailtaskagent.models import AgentAction, MailIntent, ReviewDecision, TaskStatus
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow, load_mails


SCENARIO_EXPECTATIONS = json.loads(
    (PROJECT_ROOT / "data" / "scenario_expectations.json").read_text(encoding="utf-8")
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=tmp_path / "test.db",
        confidence_threshold=0.75,
    )


def test_create_then_update_vertical_slice(settings: Settings) -> None:
    mails = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())

    created = workflow.process(mails[0])
    assert created.proposal.action == AgentAction.CREATE_TASK
    assert created.task is not None
    assert created.task["task_id"] == "TASK-001"
    assert created.task["due_date"] == "2026-08-21"

    updated = workflow.process(mails[1])
    assert updated.proposal.action == AgentAction.UPDATE_TASK
    assert updated.before is not None
    assert updated.after is not None
    assert updated.before["due_date"] == "2026-08-21"
    assert updated.after["due_date"] == "2026-08-24"
    assert updated.candidate_tasks[0].match_score == 1.0
    assert updated.candidate_tasks[0].match_reason == "동일 conversation_id"
    assert len(storage.list_histories()) == 2
    processing_results = storage.list_processing_results()
    assert [item["mail_id"] for item in processing_results] == ["MAIL-002", "MAIL-001"]
    assert processing_results[0]["result"]["proposal"]["action"] == "UPDATE_TASK"
    update_events = storage.list_events("MAIL-002")
    assert any(event["step"] == "M-02 TASK_MATCHING" for event in update_events)
    assert any(
        event["step"] == "M-04 DB_TRANSACTION" and event["status"] == "SUCCESS"
        for event in update_events
    )


def test_waiting_lifecycle_resumes_when_information_arrives(settings: Settings) -> None:
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())

    workflow.process(mails["MAIL-001"])
    waiting = workflow.process(mails["MAIL-003"])

    assert waiting.proposal.action == AgentAction.SET_WAITING
    assert waiting.before is not None
    assert waiting.after is not None
    assert waiting.before["status"] == "TODO"
    assert waiting.after["status"] == "WAITING_REPLY"
    assert waiting.after["waiting_since"] == "2026-08-19T10:00:00+09:00"

    resumed = workflow.process(mails["MAIL-004"])

    assert resumed.proposal.action == AgentAction.UPDATE_TASK
    assert resumed.before is not None
    assert resumed.after is not None
    assert resumed.before["status"] == "WAITING_REPLY"
    assert resumed.after["status"] == "IN_PROGRESS"
    assert resumed.after["waiting_since"] is None
    assert [item["action"] for item in reversed(storage.list_histories())] == [
        AgentAction.CREATE_TASK.value,
        AgentAction.SET_WAITING.value,
        AgentAction.UPDATE_TASK.value,
    ]


def test_information_mail_links_without_unjustified_state_change(settings: Settings) -> None:
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())

    created = workflow.process(mails["MAIL-001"])
    linked = workflow.process(mails["MAIL-004"])

    assert linked.proposal.action == AgentAction.LINK_TO_TASK
    assert linked.task is not None
    assert linked.task["task_id"] == created.task["task_id"]
    assert linked.before == linked.after
    assert linked.after["status"] == "TODO"
    assert storage.list_histories()[0]["action"] == AgentAction.LINK_TO_TASK.value


@pytest.mark.parametrize(
    ("decision", "expected_action", "expected_status"),
    [
        (
            ReviewDecision.APPROVE_PROPOSAL,
            AgentAction.MARK_COMPLETED,
            "COMPLETED",
        ),
        (ReviewDecision.IGNORE, AgentAction.IGNORE, "TODO"),
    ],
)
def test_completion_requires_user_approval(
    settings: Settings,
    decision: ReviewDecision,
    expected_action: AgentAction,
    expected_status: str,
) -> None:
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())

    created = workflow.process(mails["MAIL-001"])
    proposed = workflow.process(mails["MAIL-009"])

    assert proposed.proposal.action == AgentAction.MARK_COMPLETED
    assert proposed.proposal.needs_user_confirmation is True
    assert created.task is not None
    assert storage.get_task(created.task["task_id"])["status"] == "TODO"
    assert len(storage.list_pending_reviews()) == 1

    review = workflow.resolve_review(mail=mails["MAIL-009"], decision=decision)

    assert review["final_action"] == expected_action.value
    assert storage.get_task(created.task["task_id"])["status"] == expected_status
    assert storage.list_pending_reviews() == []
    assert decision.value in storage.list_histories()[0]["user_decision"]


def test_lifecycle_intent_is_not_ignored_when_live_llm_marks_it_non_request(
    settings: Settings,
) -> None:
    class LiveLikeAnalyzer(MockMailAnalyzer):
        def analyze(self, mail):
            analysis = super().analyze(mail)
            if mail.mail_id in {"MAIL-004", "MAIL-009"}:
                return analysis.model_copy(update={"is_task_request": False})
            return analysis

    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, LiveLikeAnalyzer())

    workflow.process(mails["MAIL-001"])
    workflow.process(mails["MAIL-003"])
    resumed = workflow.process(mails["MAIL-004"])
    completion = workflow.process(mails["MAIL-009"])

    assert resumed.proposal.action == AgentAction.UPDATE_TASK
    assert resumed.after["status"] == "IN_PROGRESS"
    assert completion.proposal.action == AgentAction.MARK_COMPLETED
    assert completion.proposal.needs_user_confirmation is True


def test_ambiguous_due_phrase_is_reviewed_even_if_llm_calls_it_new_task(
    settings: Settings,
) -> None:
    class LiveLikeAnalyzer(MockMailAnalyzer):
        def analyze(self, mail):
            analysis = super().analyze(mail)
            return analysis.model_copy(
                update={
                    "intent": MailIntent.NEW_TASK,
                    "confidence": 0.96,
                    "due_date": date(2026, 8, 31),
                }
            )

    mail = {
        item.mail_id: item
        for item in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }["MAIL-015"]
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, LiveLikeAnalyzer())

    result = workflow.process(mail)

    assert result.proposal.action == AgentAction.ASK_USER
    assert storage.list_tasks() == []


@pytest.mark.parametrize(
    ("decision", "expected_action", "expected_status"),
    [
        (ReviewDecision.APPROVE_PROPOSAL, AgentAction.UPDATE_TASK, "CANCELLED"),
        (ReviewDecision.IGNORE, AgentAction.IGNORE, "TODO"),
    ],
)
def test_cancellation_requires_user_approval(
    settings: Settings,
    decision: ReviewDecision,
    expected_action: AgentAction,
    expected_status: str,
) -> None:
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())

    created = workflow.process(mails["MAIL-008"])
    proposed = workflow.process(mails["MAIL-010"])

    assert proposed.proposal.action == AgentAction.ASK_USER
    assert proposed.proposal.changes["status"] == "CANCELLED"
    assert created.task is not None
    assert storage.get_task(created.task["task_id"])["status"] == "TODO"

    review = workflow.resolve_review(mail=mails["MAIL-010"], decision=decision)

    assert review["final_action"] == expected_action.value
    assert storage.get_task(created.task["task_id"])["status"] == expected_status
    assert storage.list_pending_reviews() == []


@pytest.mark.parametrize(
    ("decision", "approved_changes", "expected_action", "expected_due_date"),
    [
        (
            ReviewDecision.APPROVE_PROPOSAL,
            None,
            AgentAction.UPDATE_TASK,
            "2026-08-20",
        ),
        (
            ReviewDecision.APPROVE_PROPOSAL,
            {"due_date": "2026-08-22"},
            AgentAction.UPDATE_TASK,
            "2026-08-22",
        ),
        (ReviewDecision.IGNORE, None, AgentAction.IGNORE, "2026-08-21"),
    ],
)
def test_due_date_shortening_requires_review_and_supports_user_edit(
    settings: Settings,
    decision: ReviewDecision,
    approved_changes: dict | None,
    expected_action: AgentAction,
    expected_due_date: str,
) -> None:
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())

    created = workflow.process(mails["MAIL-001"])
    proposed = workflow.process(mails["MAIL-012"])

    assert proposed.proposal.action == AgentAction.ASK_USER
    assert proposed.proposal.changes == {"due_date": "2026-08-20"}
    assert created.task is not None
    assert storage.get_task(created.task["task_id"])["due_date"] == "2026-08-21"

    review = workflow.resolve_review(
        mail=mails["MAIL-012"],
        decision=decision,
        approved_changes=approved_changes,
    )

    assert review["final_action"] == expected_action.value
    assert storage.get_task(created.task["task_id"])["due_date"] == expected_due_date


@pytest.mark.parametrize("mail_id", ["MAIL-005", "MAIL-007"])
def test_non_task_and_prompt_injection_are_ignored(
    settings: Settings,
    mail_id: str,
) -> None:
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())

    result = workflow.process(mails[mail_id])

    assert result.proposal.action == AgentAction.IGNORE
    assert storage.list_tasks() == []
    assert storage.list_histories()[0]["action"] == AgentAction.IGNORE.value


def test_scenario_expectations_use_supported_actions_and_states() -> None:
    assert len(SCENARIO_EXPECTATIONS) == 15
    for case in SCENARIO_EXPECTATIONS:
        for action in case["expected_actions"]:
            assert action in AgentAction._value2member_map_
        state_values = []
        if case.get("expected_final_status"):
            state_values.append(case["expected_final_status"])
        state_values.extend(case.get("expected_status_sequence", []))
        if case.get("expected_final_status_before_review"):
            state_values.append(case["expected_final_status_before_review"])
        if case.get("expected_final_status_after_approval"):
            state_values.append(case["expected_final_status_after_approval"])
        for status in state_values:
            assert status in TaskStatus._value2member_map_


def test_mock_scenario_evaluation_reports_complete_evidence(settings: Settings) -> None:
    report = run_scenario_evaluation(settings, MockMailAnalyzer(), mode="MOCK")

    assert report["case_count"] == 15
    assert report["passed_count"] == 15
    assert report["scenario_pass_rate"] == 1
    assert report["action_step_accuracy"] == 1
    assert report["total_action_steps"] == 28
    assert report["review_rate"] == pytest.approx(7 / 15)
    assert all(row["error"] == "-" for row in report["rows"])


def test_checked_in_live_evaluation_evidence_is_complete() -> None:
    report = load_saved_evaluation_report(
        PROJECT_ROOT / "evidence" / "live_evaluation_2026-08-26.json"
    )

    assert report["mode"] == "LIVE"
    assert report["case_count"] == report["passed_count"] == 15
    assert report["total_action_steps"] == 28
    assert len(report["rows"]) == 15
    assert all(row["passed"] and row["error"] == "-" for row in report["rows"])


@pytest.mark.parametrize(
    "case",
    SCENARIO_EXPECTATIONS,
    ids=[case["case_id"] for case in SCENARIO_EXPECTATIONS],
)
def test_expected_business_scenario_actions(settings: Settings, case: dict) -> None:
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())

    results = [workflow.process(mails[mail_id]) for mail_id in case["mail_ids"]]

    assert [result.proposal.action.value for result in results] == case["expected_actions"]
    if case.get("review_required"):
        assert results[-1].proposal.needs_user_confirmation is True
    if "expected_candidate_count" in case:
        assert len(results[-1].candidate_tasks) == case["expected_candidate_count"]
    if "expected_task_count" in case:
        assert len(storage.list_tasks()) == case["expected_task_count"]
    if "expected_history_count" in case:
        assert len(storage.list_histories()) == case["expected_history_count"]
    if case.get("second_result_duplicate"):
        assert results[-1].duplicate is True

    tasks = storage.list_tasks()
    if "expected_final_status" in case and tasks:
        assert tasks[0]["status"] == case["expected_final_status"]
    if "expected_final_status_before_review" in case and tasks:
        assert tasks[0]["status"] == case["expected_final_status_before_review"]
    if "expected_due_date" in case and tasks:
        assert tasks[0]["due_date"] == case["expected_due_date"]
    if "expected_due_date_before_review" in case and tasks:
        assert tasks[0]["due_date"] == case["expected_due_date_before_review"]
    if "expected_status_sequence" in case:
        assert [result.task["status"] for result in results] == case["expected_status_sequence"]


def test_duplicate_mail_does_not_add_history(settings: Settings) -> None:
    class CountingAnalyzer(MockMailAnalyzer):
        def __init__(self):
            self.calls = 0

        def analyze(self, mail):
            self.calls += 1
            return super().analyze(mail)

    mail = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[0]
    storage = SQLiteStorage(settings.database_path)
    analyzer = CountingAnalyzer()
    workflow = MailTaskWorkflow(settings, storage, analyzer)

    workflow.process(mail)
    duplicate = workflow.process(mail)

    assert duplicate.duplicate is True
    assert analyzer.calls == 1
    assert len(storage.list_tasks()) == 1
    assert len(storage.list_histories()) == 1
    assert any(
        event["step"] == "DUPLICATE_CHECK" and event["status"] == "DUPLICATE"
        for event in storage.list_events(mail.mail_id)
    )


def test_analyzer_failure_does_not_change_database(settings: Settings) -> None:
    class FailingAnalyzer:
        def analyze(self, mail):
            raise TimeoutError("simulated timeout")

    mail = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[0]
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, FailingAnalyzer())

    with pytest.raises(TimeoutError):
        workflow.process(mail)

    assert storage.list_tasks() == []
    assert storage.list_histories() == []
    assert storage.is_processed(mail.mail_id) is False
    assert any(
        event["step"] == "PROCESS_FAILED" and event["level"] == "ERROR"
        for event in storage.list_events(mail.mail_id)
    )
    assert any(
        event["step"] == "M-01 LLM_ANALYSIS" and event["status"] == "FAILED"
        for event in storage.list_events(mail.mail_id)
    )


@pytest.mark.parametrize(
    ("decision", "expected_action", "expected_task_count"),
    [
        (ReviewDecision.LINK_EXISTING, AgentAction.LINK_TO_TASK, 2),
        (ReviewDecision.CREATE_NEW, AgentAction.CREATE_TASK, 3),
        (ReviewDecision.IGNORE, AgentAction.IGNORE, 2),
    ],
)
def test_ask_user_review_flow(
    settings: Settings,
    decision: ReviewDecision,
    expected_action: AgentAction,
    expected_task_count: int,
) -> None:
    mails = {mail.mail_id: mail for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")}
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())

    workflow.process(mails["MAIL-001"])
    workflow.process(mails["MAIL-008"])
    ambiguous = workflow.process(mails["MAIL-006"])

    assert ambiguous.proposal.action == AgentAction.ASK_USER
    assert len(ambiguous.candidate_tasks) == 2
    assert all(candidate.match_score > 0 for candidate in ambiguous.candidate_tasks)
    assert all(candidate.match_reason for candidate in ambiguous.candidate_tasks)
    assert len(storage.list_pending_reviews()) == 1

    target_task_id = ambiguous.candidate_tasks[0].task_id if decision == ReviewDecision.LINK_EXISTING else None
    review = workflow.resolve_review(
        mail=mails["MAIL-006"],
        decision=decision,
        target_task_id=target_task_id,
        new_task_title="사용자가 확정한 DDC 신규 업무"
        if decision == ReviewDecision.CREATE_NEW
        else None,
    )

    assert review["final_action"] == expected_action.value
    assert len(storage.list_tasks()) == expected_task_count
    assert storage.list_pending_reviews() == []
    latest_history = storage.list_histories()[0]
    assert latest_history["action"] == expected_action.value
    assert decision.value in latest_history["user_decision"]
    assert any(
        event["step"] == "M-05 USER_REVIEW" and event["status"] == "SUCCESS"
        for event in storage.list_events("MAIL-006")
    )


def test_processing_log_redacts_secrets(settings: Settings) -> None:
    storage = SQLiteStorage(settings.database_path)
    storage.initialize()
    storage.append_event(
        case_id="CASE-SECRET",
        mail_id="MAIL-SECRET",
        step="SECURITY_TEST",
        status="FAILED",
        message="api-key: atl-secret-value",
        details={"api_key": "atl-secret-value", "authorization": "Bearer token-value"},
    )

    event = storage.list_events("MAIL-SECRET")[0]
    serialized = f"{event['message']} {event['details_json']}"
    assert "atl-secret-value" not in serialized
    assert "token-value" not in serialized
    assert "[REDACTED]" in serialized
