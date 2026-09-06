from __future__ import annotations

import base64
from email import message_from_bytes
from email.header import decode_header, make_header

import pytest

from mailtaskagent.approved_send_service import GmailApprovedSendService
from mailtaskagent.config import Settings
from mailtaskagent.gmail_send import (
    GmailApprovedSendSettings,
    GmailReplySender,
    GmailSendResult,
    gmail_reply_subject,
    load_gmail_approved_send_settings,
    source_gmail_ids,
)
from mailtaskagent.llm_client import MockMailAnalyzer
from mailtaskagent.models import (
    ActionProposal,
    AgentAction,
    MailAnalysis,
    MailDirection,
    MailInput,
    MailIntent,
    TaskStatus,
)
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow


class _Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _GmailApi:
    def __init__(self):
        self.sent_body = None
        self.get_kwargs = None

    def users(self):
        return self

    def messages(self):
        return self

    def get(self, **kwargs):
        self.get_kwargs = kwargs
        return _Request(
            {
                "id": "source-1",
                "threadId": "thread-1",
                "payload": {
                    "headers": [
                        {"name": "Message-ID", "value": "<source@example.test>"},
                        {"name": "References", "value": "<older@example.test>"},
                        {"name": "Subject", "value": "업무 일정 확인"},
                    ]
                },
            }
        )

    def getProfile(self, **kwargs):
        return _Request({"emailAddress": "worker@example.test"})

    def send(self, **kwargs):
        self.sent_body = kwargs
        return _Request({"id": "sent-1", "threadId": "thread-1"})


class _FakeSender:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = []

    def send_reply(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return GmailSendResult(
            message_id="sent-1",
            thread_id=kwargs["thread_id"],
            sender="worker@example.test",
        )


def _settings(tmp_path) -> Settings:
    return Settings(
        api_url="https://example.test",
        api_key="",
        model="test-model",
        api_version="test-version",
        timeout_seconds=1,
        use_mock=True,
        database_path=tmp_path / "send.db",
        confidence_threshold=0.75,
    )


def _draft_fixture(tmp_path):
    storage = SQLiteStorage(tmp_path / "send.db")
    storage.initialize()
    mail = MailInput(
        mail_id="GMAIL-source-1",
        conversation_id="GMAIL-THREAD-thread-1",
        direction=MailDirection.INBOUND,
        sender="requester@example.test",
        recipients=["worker@example.test"],
        received_at="2026-09-06T09:00:00+09:00",
        subject="업무 일정 확인",
        body="9월 10일 작업 가능한지 회신해 주세요.",
    )
    task, _, _ = storage.apply(
        "SEND-CASE-001",
        mail,
        MailAnalysis(
            is_task_request=True,
            intent=MailIntent.NEW_TASK,
            task_title="작업 일정 회신",
            request_summary=mail.body,
            requester=mail.sender,
            reply_required=True,
            reason="회신 테스트",
            confidence=0.99,
        ),
        ActionProposal(
            action=AgentAction.CREATE_TASK,
            task_payload={
                "conversation_id": mail.conversation_id,
                "title": "작업 일정 회신",
                "description": mail.body,
                "requester": mail.sender,
                "due_date": None,
                "reply_required": True,
                "status": TaskStatus.TODO.value,
            },
            reason="회신 테스트 Task 생성",
            confidence=0.99,
        ),
        [],
    )
    draft = storage.create_reply_plan(
        task_id=task["task_id"],
        source_mail_id=mail.mail_id,
        reply_action="DATE_REPLY",
        question="가능일을 선택하세요.",
        draft_body=None,
        reason="날짜 입력 필요",
        confidence=0.95,
    )
    draft = storage.update_reply_draft(
        draft["reply_id"],
        draft_body="안녕하세요. 9월 10일 작업 가능합니다. 감사합니다.",
        user_input="2026-09-10",
        user_edited=True,
    )
    send_settings = GmailApprovedSendSettings(
        enabled=True,
        allowed_recipients=("requester@example.test",),
    )
    return storage, mail, task, draft, send_settings


def test_gmail_reply_sender_builds_plain_text_threaded_reply() -> None:
    api = _GmailApi()
    result = GmailReplySender(api).send_reply(
        source_message_id="source-1",
        thread_id="thread-1",
        recipient="requester@example.test",
        subject="업무 일정 확인",
        body="9월 10일 가능합니다.",
    )

    assert result == GmailSendResult("sent-1", "thread-1", "worker@example.test")
    assert api.get_kwargs["metadataHeaders"] == ["Message-ID", "References", "Subject"]
    assert api.sent_body["userId"] == "me"
    assert api.sent_body["body"]["threadId"] == "thread-1"
    decoded = base64.urlsafe_b64decode(api.sent_body["body"]["raw"])
    message = message_from_bytes(decoded)
    assert message["To"] == "requester@example.test"
    assert str(make_header(decode_header(message["Subject"]))) == "Re: 업무 일정 확인"
    assert message["In-Reply-To"] == "<source@example.test>"
    assert "<older@example.test> <source@example.test>" == message["References"]
    assert "9월 10일 가능합니다." in message.get_payload(decode=True).decode("utf-8")


def test_send_settings_require_valid_exact_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_APPROVED_SEND_ENABLED", "true")
    monkeypatch.setenv(
        "GMAIL_SEND_ALLOWED_RECIPIENTS",
        "requester@example.test, second@example.test",
    )

    settings = load_gmail_approved_send_settings()

    assert settings.enabled is True
    assert settings.recipient_allowed("REQUESTER@example.test") is True
    assert settings.recipient_allowed("other@example.test") is False
    monkeypatch.setenv("GMAIL_SEND_ALLOWED_RECIPIENTS", "not-an-address")
    with pytest.raises(ValueError, match="invalid email"):
        load_gmail_approved_send_settings()


def test_gmail_reply_subject_and_source_ids_are_fail_closed() -> None:
    assert gmail_reply_subject("업무 확인") == "Re: 업무 확인"
    assert gmail_reply_subject("RE: 업무 확인") == "RE: 업무 확인"
    assert source_gmail_ids(
        "GMAIL-source-1", "GMAIL-THREAD-thread-1"
    ) == ("source-1", "thread-1")
    with pytest.raises(ValueError, match="Gmail source"):
        source_gmail_ids("MAIL-001", "GMAIL-THREAD-thread-1")


def test_approved_send_requires_explicit_confirmation(tmp_path) -> None:
    storage, _, _, draft, settings = _draft_fixture(tmp_path)
    sender = _FakeSender()
    service = GmailApprovedSendService(storage, sender, settings)

    with pytest.raises(ValueError, match="명시적으로 승인"):
        service.send(draft["reply_id"], user_confirmed=False)

    assert sender.calls == []
    assert storage.get_reply_send(draft["reply_id"]) is None


def test_approved_send_requires_allowlisted_original_sender(tmp_path) -> None:
    storage, _, _, draft, _ = _draft_fixture(tmp_path)
    sender = _FakeSender()
    service = GmailApprovedSendService(
        storage,
        sender,
        GmailApprovedSendSettings(enabled=True, allowed_recipients=()),
    )

    with pytest.raises(ValueError, match="Allowlist"):
        service.send(draft["reply_id"], user_confirmed=True)

    assert sender.calls == []


def test_approved_send_records_outbound_mail_and_sets_waiting(tmp_path) -> None:
    storage, _, task, draft, settings = _draft_fixture(tmp_path)
    sender = _FakeSender()
    service = GmailApprovedSendService(storage, sender, settings)

    completed = service.send(draft["reply_id"], user_confirmed=True)

    assert len(sender.calls) == 1
    assert completed["send"]["status"] == "SENT"
    assert completed["send"]["gmail_message_id"] == "GMAIL-sent-1"
    assert completed["task"]["status"] == TaskStatus.WAITING_REPLY.value
    assert storage.get_reply_draft(draft["reply_id"])["status"] == "SENT"
    stored = storage.get_processing_result("GMAIL-sent-1")
    assert stored["action"] == AgentAction.SET_WAITING.value
    assert stored["validation_result"] == {"user_approved": True}
    histories = storage.list_histories()
    assert histories[0]["mail_id"] == "GMAIL-sent-1"
    assert "APPROVE_GMAIL_SEND" in histories[0]["user_decision"]
    send_events = storage.list_events(mail_id="GMAIL-source-1")
    assert next(
        event for event in send_events if event["step"] == "GMAIL_SEND_GUARD"
    )["status"] == "ACCEPTED"
    assert next(
        event for event in send_events if event["step"] == "GMAIL_SEND_EXECUTION"
    )["status"] == "SUCCESS"

    duplicate = MailTaskWorkflow(
        _settings(tmp_path), storage, MockMailAnalyzer()
    ).process(completed["mail"])
    assert duplicate.duplicate is True
    assert storage.get_task(task["task_id"])["status"] == TaskStatus.WAITING_REPLY.value


def test_approved_send_blocks_duplicate_click_before_second_api_call(tmp_path) -> None:
    storage, _, _, draft, settings = _draft_fixture(tmp_path)
    sender = _FakeSender()
    service = GmailApprovedSendService(storage, sender, settings)
    service.send(draft["reply_id"], user_confirmed=True)

    with pytest.raises(ValueError, match="이미 발송을 시도"):
        service.send(draft["reply_id"], user_confirmed=True)

    assert len(sender.calls) == 1


def test_gmail_api_failure_never_changes_task_or_retries(tmp_path) -> None:
    storage, _, task, draft, settings = _draft_fixture(tmp_path)
    sender = _FakeSender(TimeoutError("provider detail must stay hidden"))
    service = GmailApprovedSendService(storage, sender, settings)

    with pytest.raises(ValueError, match="보낸편지함을 확인") as error:
        service.send(draft["reply_id"], user_confirmed=True)

    assert "provider detail" not in str(error.value)
    assert len(sender.calls) == 1
    assert storage.get_task(task["task_id"])["status"] == TaskStatus.TODO.value
    assert storage.get_reply_send(draft["reply_id"])["status"] == "FAILED"
    events = storage.list_events(mail_id="GMAIL-source-1")
    failed = next(event for event in events if event["step"] == "GMAIL_SEND_EXECUTION")
    assert failed["status"] == "FAILED"
    assert "provider detail" not in failed["details_json"]


def test_terminal_task_is_blocked_before_gmail_api(tmp_path) -> None:
    storage, _, task, draft, settings = _draft_fixture(tmp_path)
    storage.update_task_by_user(
        task["task_id"],
        title=task["title"],
        description=task["description"],
        due_date=task["due_date"],
        status=TaskStatus.COMPLETED.value,
        reply_required=task["reply_required"],
    )
    sender = _FakeSender()

    with pytest.raises(ValueError, match="status transition"):
        GmailApprovedSendService(storage, sender, settings).send(
            draft["reply_id"], user_confirmed=True
        )

    assert sender.calls == []
