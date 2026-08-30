from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

import pytest

from mailtaskagent.gmail_source import (
    GmailReadOnlySource,
    GmailSourceSettings,
    gmail_message_to_mail_input,
    load_gmail_source_settings,
)
from mailtaskagent.config import PROJECT_ROOT, Settings
from mailtaskagent.llm_client import MockMailAnalyzer
from mailtaskagent.models import MailDirection
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow, load_mails


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _message(
    message_id: str,
    *,
    thread_id: str = "thread-1",
    internal_date: str = "1787792400000",
    label_ids: list[str] | None = None,
    body: str = "합성 테스트 업무를 확인해 주세요.",
    mime_type: str = "text/plain",
) -> dict:
    return {
        "id": message_id,
        "threadId": thread_id,
        "internalDate": internal_date,
        "labelIds": label_ids or ["INBOX", "Label_Demo"],
        "payload": {
            "mimeType": mime_type,
            "headers": [
                {"name": "From", "value": "요청자 <requester@example.test>"},
                {"name": "To", "value": "담당자 <worker@example.test>"},
                {"name": "Subject", "value": "합성 Gmail 업무 요청"},
            ],
            "body": {"data": _encoded(body)},
        },
    }


class _Request:
    def __init__(self, response: dict | Exception) -> None:
        self.response = response

    def execute(self) -> dict:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _HttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.resp = type("Response", (), {"status": status})()


class _MessagesApi:
    def __init__(self, messages: dict[str, dict]) -> None:
        self.raw_messages = messages
        self.list_kwargs: dict | None = None
        self.get_kwargs: list[dict] = []

    def list(self, **kwargs) -> _Request:
        self.list_kwargs = kwargs
        return _Request({"messages": [{"id": key} for key in self.raw_messages]})

    def get(self, **kwargs) -> _Request:
        self.get_kwargs.append(kwargs)
        return _Request(self.raw_messages[kwargs["id"]])


class _ThreadsApi:
    def __init__(self, threads: dict[str, dict | Exception]) -> None:
        self.raw_threads = threads
        self.get_kwargs: list[dict] = []

    def get(self, **kwargs) -> _Request:
        self.get_kwargs.append(kwargs)
        return _Request(self.raw_threads[kwargs["id"]])


class _FakeService:
    def __init__(
        self,
        messages: dict[str, dict],
        threads: dict[str, dict | Exception] | None = None,
    ) -> None:
        self.messages_api = _MessagesApi(messages)
        self.threads_api = _ThreadsApi(threads or {})

    def users(self) -> "_FakeService":
        return self

    def messages(self) -> _MessagesApi:
        return self.messages_api

    def threads(self) -> _ThreadsApi:
        return self.threads_api


def test_gmail_message_maps_to_common_inbound_schema() -> None:
    mail = gmail_message_to_mail_input(_message("message-1"))

    assert mail.mail_id == "GMAIL-message-1"
    assert mail.conversation_id == "GMAIL-THREAD-thread-1"
    assert mail.direction == MailDirection.INBOUND
    assert mail.sender == "requester@example.test"
    assert mail.recipients == ["worker@example.test"]
    assert mail.subject == "합성 Gmail 업무 요청"
    assert mail.body == "합성 테스트 업무를 확인해 주세요."
    assert mail.received_at is not None
    assert mail.sent_at is None


def test_gmail_message_maps_sent_html_to_outbound_plain_text() -> None:
    mail = gmail_message_to_mail_input(
        _message(
            "message-2",
            label_ids=["SENT"],
            body="<p>자료를 <strong>요청</strong>했습니다.</p>",
            mime_type="text/html",
        )
    )

    assert mail.direction == MailDirection.OUTBOUND
    assert mail.received_at is None
    assert mail.sent_at is not None
    assert mail.body == "자료를\n요청\n했습니다."


def test_gmail_message_strips_quoted_reply_history() -> None:
    mail = gmail_message_to_mail_input(
        _message(
            "message-reply",
            body=(
                "[GL-003] 확인했습니다. 현재 요청 내용은 그대로 진행해 주세요.\n\n"
                "2026년 8월 28일 (금) 오후 7:47, 요청자 <requester@example.test>님이 작성:\n"
                "> [GL-002] 공유 기한을 2026-09-07로 변경해 주세요."
            ),
        )
    )

    assert mail.body == "[GL-003] 확인했습니다. 현재 요청 내용은 그대로 진행해 주세요."


def test_gmail_source_uses_restricted_query_and_sorts_oldest_first(tmp_path) -> None:
    service = _FakeService(
        {
            "newer": _message("newer", internal_date="1787796000000"),
            "older": _message("older", internal_date="1787792400000"),
        }
    )
    settings = GmailSourceSettings(
        credentials_path=tmp_path / "credentials.json",
        token_path=tmp_path / "token.json",
        query="label:MailTaskAgent-Demo",
        max_results=10,
    )

    mails = GmailReadOnlySource(service, settings).load()

    assert [mail.mail_id for mail in mails] == ["GMAIL-older", "GMAIL-newer"]
    assert service.messages_api.list_kwargs == {
        "userId": "me",
        "q": "label:MailTaskAgent-Demo",
        "maxResults": 10,
        "includeSpamTrash": False,
    }
    assert all(call["format"] == "full" for call in service.messages_api.get_kwargs)


def test_gmail_source_follows_only_task_linked_threads_in_both_directions(
    tmp_path,
) -> None:
    entry = _message("entry", thread_id="tracked-thread")
    outbound_reply = _message(
        "sent-reply",
        thread_id="tracked-thread",
        internal_date="1787796000000",
        label_ids=["SENT"],
        body="요청하신 자료를 확인한 뒤 회신드리겠습니다.",
    )
    inbound_reply = _message(
        "inbound-reply",
        thread_id="tracked-thread",
        internal_date="1787799600000",
        label_ids=["INBOX"],
        body="추가 자료를 전달드립니다.",
    )
    service = _FakeService(
        {"entry": entry},
        {
            "tracked-thread": {
                "messages": [entry, outbound_reply, inbound_reply],
            }
        },
    )
    settings = GmailSourceSettings(
        credentials_path=tmp_path / "credentials.json",
        token_path=tmp_path / "token.json",
        query="label:MailTaskAgent-Demo",
        max_results=10,
    )

    mails = GmailReadOnlySource(
        service,
        settings,
        tracked_conversation_ids=[
            "GMAIL-THREAD-tracked-thread",
            "USER-CONVERSATION-not-gmail",
            "GMAIL-THREAD-tracked-thread",
        ],
    ).load()

    assert [mail.mail_id for mail in mails] == [
        "GMAIL-entry",
        "GMAIL-sent-reply",
        "GMAIL-inbound-reply",
    ]
    assert [mail.direction for mail in mails] == [
        MailDirection.INBOUND,
        MailDirection.OUTBOUND,
        MailDirection.INBOUND,
    ]
    assert service.threads_api.get_kwargs == [
        {"userId": "me", "id": "tracked-thread", "format": "full"}
    ]


def test_gmail_source_skips_only_missing_tracked_thread(tmp_path) -> None:
    service = _FakeService(
        {"entry": _message("entry", thread_id="available-thread")},
        {
            "available-thread": {
                "messages": [_message("entry", thread_id="available-thread")]
            },
            "deleted-thread": _HttpError(404),
        },
    )
    settings = GmailSourceSettings(
        credentials_path=tmp_path / "credentials.json",
        token_path=tmp_path / "token.json",
        query="label:MailTaskAgent-Demo",
        max_results=10,
    )
    source = GmailReadOnlySource(
        service,
        settings,
        tracked_conversation_ids=[
            "GMAIL-THREAD-available-thread",
            "GMAIL-THREAD-deleted-thread",
        ],
    )

    mails = source.load()

    assert [mail.mail_id for mail in mails] == ["GMAIL-entry"]
    assert source.missing_thread_count == 1


def test_gmail_source_does_not_hide_tracked_thread_auth_failure(tmp_path) -> None:
    service = _FakeService(
        {},
        {"forbidden-thread": _HttpError(403)},
    )
    settings = GmailSourceSettings(
        credentials_path=tmp_path / "credentials.json",
        token_path=tmp_path / "token.json",
        query="label:MailTaskAgent-Demo",
        max_results=10,
    )
    source = GmailReadOnlySource(
        service,
        settings,
        tracked_conversation_ids=["GMAIL-THREAD-forbidden-thread"],
    )

    with pytest.raises(_HttpError, match="HTTP 403"):
        source.load()


def test_gmail_settings_reject_unrestricted_query(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_QUERY", " ")

    with pytest.raises(ValueError, match="must restrict"):
        load_gmail_source_settings()


def test_gmail_settings_caps_message_count(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GMAIL_QUERY", "label:MailTaskAgent-Demo")
    monkeypatch.setenv("GMAIL_MAX_RESULTS", "101")

    with pytest.raises(ValueError, match="between 1 and 100"):
        load_gmail_source_settings()


class _GmailScenarioAnalyzer:
    """Reuse deterministic scenarios after the Gmail adapter changes mail IDs."""

    def __init__(self) -> None:
        self.delegate = MockMailAnalyzer()

    def analyze(self, mail):
        original_id = mail.mail_id.removeprefix("GMAIL-")
        return self.delegate.analyze(mail.model_copy(update={"mail_id": original_id}))


def _gmail_payload_from_mail(mail) -> dict:
    occurred_at = mail.received_at or mail.sent_at
    assert occurred_at is not None
    timestamp = datetime.fromisoformat(str(occurred_at).replace("Z", "+00:00"))
    headers = [
        {"name": "From", "value": mail.sender},
        {"name": "To", "value": ", ".join(mail.recipients)},
        {"name": "Subject", "value": mail.subject},
    ]
    return {
        "id": mail.mail_id,
        "threadId": mail.conversation_id,
        "internalDate": str(int(timestamp.timestamp() * 1000)),
        "labelIds": ["SENT"] if mail.direction == MailDirection.OUTBOUND else ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": headers,
            "body": {"data": _encoded(mail.body)},
        },
    }


@pytest.mark.parametrize(
    "scenario",
    json.loads(
        (PROJECT_ROOT / "data" / "scenario_expectations.json").read_text(
            encoding="utf-8"
        )
    ),
    ids=lambda item: item["case_id"],
)
def test_all_core_scenarios_pass_through_gmail_adapter_contract(
    scenario: dict, tmp_path: Path
) -> None:
    source_mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    settings = Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=tmp_path / f"{scenario['case_id']}.db",
        confidence_threshold=0.75,
    )
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, _GmailScenarioAnalyzer())

    actual_actions = []
    duplicate_flags = []
    for mail_id in scenario["mail_ids"]:
        adapted = gmail_message_to_mail_input(
            _gmail_payload_from_mail(source_mails[mail_id])
        )
        result = workflow.process(adapted)
        actual_actions.append(result.proposal.action.value)
        duplicate_flags.append(result.duplicate)

    assert actual_actions == scenario["expected_actions"]
    if scenario.get("second_result_duplicate"):
        assert duplicate_flags[-1] is True
    if "expected_task_count" in scenario:
        assert len(storage.list_tasks()) == scenario["expected_task_count"]
    if "expected_history_count" in scenario:
        assert len(storage.list_histories()) == scenario["expected_history_count"]
