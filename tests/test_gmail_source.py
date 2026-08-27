from __future__ import annotations

import base64
from pathlib import Path

import pytest

from mailtaskagent.gmail_source import (
    GmailReadOnlySource,
    GmailSourceSettings,
    gmail_message_to_mail_input,
    load_gmail_source_settings,
)
from mailtaskagent.models import MailDirection


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
    def __init__(self, response: dict) -> None:
        self.response = response

    def execute(self) -> dict:
        return self.response


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


class _FakeService:
    def __init__(self, messages: dict[str, dict]) -> None:
        self.messages_api = _MessagesApi(messages)

    def users(self) -> "_FakeService":
        return self

    def messages(self) -> _MessagesApi:
        return self.messages_api


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


def test_gmail_settings_reject_unrestricted_query(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_QUERY", " ")

    with pytest.raises(ValueError, match="must restrict"):
        load_gmail_source_settings()


def test_gmail_settings_caps_message_count(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GMAIL_QUERY", "label:MailTaskAgent-Demo")
    monkeypatch.setenv("GMAIL_MAX_RESULTS", "101")

    with pytest.raises(ValueError, match="between 1 and 100"):
        load_gmail_source_settings()
