import json
from types import SimpleNamespace

from mailtaskagent.config import Settings
from mailtaskagent.models import (
    ActionProposal,
    AgentAction,
    MailAnalysis,
    MailDirection,
    MailInput,
    MailIntent,
    ReplyAction,
    ReplyPlan,
)
from mailtaskagent.reply_assistant import AzureReplyAssistant, MockReplyAssistant
from mailtaskagent.reply_service import MailToActionDraftService
from mailtaskagent.storage import SQLiteStorage


def _mail(body: str, *, mail_id: str = "REPLY-MAIL-001") -> MailInput:
    return MailInput(
        mail_id=mail_id,
        conversation_id="REPLY-THREAD-001",
        direction=MailDirection.INBOUND,
        sender="requester@example.test",
        recipients=["user@example.test"],
        received_at="2026-09-06T09:00:00+09:00",
        subject="회신 요청",
        body=body,
    )


def _storage_with_task(tmp_path, mail: MailInput) -> tuple[SQLiteStorage, dict]:
    storage = SQLiteStorage(tmp_path / "reply.db")
    storage.initialize()
    task, _, _ = storage.apply(
        "REPLY-CASE-001",
        mail,
        MailAnalysis(
            is_task_request=True,
            intent=MailIntent.NEW_TASK,
            task_title="회신 검증 업무",
            request_summary=mail.body,
            requester=mail.sender,
            due_date=None,
            reply_required=True,
            reason="테스트 업무",
            confidence=0.99,
        ),
        ActionProposal(
            action=AgentAction.CREATE_TASK,
            task_payload={
                "conversation_id": mail.conversation_id,
                "title": "회신 검증 업무",
                "description": mail.body,
                "requester": mail.sender,
                "due_date": None,
                "reply_required": True,
                "status": "TODO",
            },
            changes={},
            reason="테스트 업무 생성",
            confidence=0.99,
        ),
        [],
    )
    return storage, task


def test_date_reply_requires_user_input_and_persists_draft(tmp_path) -> None:
    storage, task = _storage_with_task(
        tmp_path,
        _mail("작업 가능 일정을 회신해 주세요."),
    )
    service = MailToActionDraftService(storage, MockReplyAssistant())

    plan = service.prepare(task["task_id"])
    draft = service.compose(plan["reply_id"], "2026-09-10")

    assert plan["reply_action"] == ReplyAction.DATE_REPLY.value
    assert plan["status"] == "NEEDS_INPUT"
    assert draft["status"] == "DRAFTED"
    assert "2026-09-10" in draft["draft_body"]
    assert "전송" not in draft["status"]


def test_simple_ack_is_created_without_sending(tmp_path) -> None:
    storage, task = _storage_with_task(
        tmp_path,
        _mail("내용 확인 부탁드립니다."),
    )
    service = MailToActionDraftService(storage, MockReplyAssistant())

    record = service.prepare(task["task_id"])

    assert record["reply_action"] == ReplyAction.SIMPLE_ACK.value
    assert record["status"] == "DRAFTED"
    assert "확인했습니다" in record["draft_body"]
    assert storage.get_task(task["task_id"])["status"] == "TODO"


def test_low_confidence_reply_plan_fails_closed(tmp_path) -> None:
    storage, task = _storage_with_task(tmp_path, _mail("회신이 필요합니다."))

    class LowConfidenceAssistant(MockReplyAssistant):
        def plan(self, mail, task_context):
            return ReplyPlan(
                action=ReplyAction.DRAFT_REPLY,
                confidence=0.4,
                reason="판단 근거 부족",
                draft_body="임시 초안",
            )

    record = MailToActionDraftService(
        storage, LowConfidenceAssistant(), confidence_threshold=0.75
    ).prepare(task["task_id"])

    assert record["reply_action"] == ReplyAction.ASK_USER.value
    assert record["status"] == "ASK_USER"
    assert record["draft_body"] is None


def test_reply_agent_failure_fails_closed_without_task_change(tmp_path) -> None:
    storage, task = _storage_with_task(tmp_path, _mail("회신이 필요합니다."))

    class FailingAssistant(MockReplyAssistant):
        def plan(self, mail, task_context):
            raise TimeoutError("synthetic failure")

    record = MailToActionDraftService(storage, FailingAssistant()).prepare(
        task["task_id"]
    )

    assert record["reply_action"] == ReplyAction.ASK_USER.value
    assert "TimeoutError" not in record["reason"]
    assert storage.get_task(task["task_id"])["status"] == "TODO"


def test_user_can_edit_saved_draft_with_audit_flag(tmp_path) -> None:
    storage, task = _storage_with_task(
        tmp_path,
        _mail("내용 확인 부탁드립니다."),
    )
    service = MailToActionDraftService(storage, MockReplyAssistant())
    record = service.prepare(task["task_id"])

    updated = service.save_user_edit(record["reply_id"], "수정한 회신 초안입니다.")

    assert updated["draft_body"] == "수정한 회신 초안입니다."
    assert updated["user_edited"] is True
    assert storage.list_reply_drafts(task["task_id"])[0]["reply_id"] == record["reply_id"]


def test_reply_compose_failure_keeps_plan_and_task_unchanged(tmp_path) -> None:
    storage, task = _storage_with_task(
        tmp_path,
        _mail("작업 가능 일정을 회신해 주세요."),
    )

    class FailingComposeAssistant(MockReplyAssistant):
        def compose(self, mail, task_context, plan, user_input):
            raise TimeoutError("sensitive provider detail")

    service = MailToActionDraftService(storage, FailingComposeAssistant())
    plan = service.prepare(task["task_id"])

    try:
        service.compose(plan["reply_id"], "2026-09-10")
    except ValueError as exc:
        assert "sensitive provider detail" not in str(exc)
        assert "초안 생성을 중지" in str(exc)
    else:
        raise AssertionError("Reply compose failure must be fail-closed")

    assert storage.get_reply_draft(plan["reply_id"])["status"] == "NEEDS_INPUT"
    assert storage.get_task(task["task_id"])["status"] == "TODO"


def test_azure_reply_assistant_uses_structured_untrusted_context(tmp_path) -> None:
    settings = Settings(
        api_url="https://example.test",
        api_key="test-key",
        model="test-model",
        api_version="test-version",
        timeout_seconds=1,
        use_mock=False,
        database_path=tmp_path / "unused.db",
        confidence_threshold=0.75,
    )
    contents = iter(
        [
            json.dumps(
                {
                    "action": "DATE_REPLY",
                    "confidence": 0.91,
                    "reason": "작업 가능일 입력 필요",
                    "question": "가능일을 선택해 주세요.",
                    "draft_body": None,
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {"body": "안녕하세요. 9월 10일 진행 가능합니다. 감사합니다."},
                ensure_ascii=False,
            ),
        ]
    )
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(contents)))]
        )

    assistant = AzureReplyAssistant(settings)
    assistant.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    mail = _mail("작업 가능 일정을 회신해 주세요.")
    context = {
        "task": {"task_id": "TASK-001", "status": "TODO", "title": "작업"},
        "recent_histories": [],
        "linked_mails": [],
    }

    plan = assistant.plan(mail, context)
    draft = assistant.compose(mail, context, plan, "9월 10일")

    assert plan.action == ReplyAction.DATE_REPLY
    assert "9월 10일" in draft.body
    assert "신뢰할 수 없는" in calls[0]["messages"][0]["content"]
    assert "직접 발송" in calls[0]["messages"][0]["content"]
    assert calls[0]["response_format"] == {"type": "json_object"}
