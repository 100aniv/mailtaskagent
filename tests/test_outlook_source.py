from __future__ import annotations

import pytest

from mailtaskagent.models import MailDirection
from mailtaskagent.outlook_source import (
    GRAPH_MESSAGE_SELECT,
    OutlookGraphReadOnlySource,
    OutlookSourceSettings,
    graph_message_to_mail_input,
    load_outlook_source_settings,
)


def _recipient(address: str, name: str = "테스트 사용자") -> dict:
    return {"emailAddress": {"name": name, "address": address}}


def _message(
    message_id: str,
    *,
    conversation_id: str = "conversation-1",
    received_at: str = "2026-08-28T01:00:00Z",
    sent_at: str = "2026-08-28T01:01:00Z",
    body: str = "<p>합성 Outlook 업무를 <strong>확인</strong>해 주세요.</p>",
    content_type: str = "html",
) -> dict:
    return {
        "id": message_id,
        "conversationId": conversation_id,
        "internetMessageId": f"<{message_id}@example.test>",
        "receivedDateTime": received_at,
        "sentDateTime": sent_at,
        "from": _recipient("requester@example.test", "요청자"),
        "sender": _recipient("requester@example.test", "요청자"),
        "toRecipients": [_recipient("worker@example.test", "담당자")],
        "ccRecipients": [_recipient("observer@example.test", "참조자")],
        "bccRecipients": [],
        "subject": "합성 Outlook 업무 요청",
        "body": {"contentType": content_type, "content": body},
    }


class _FakeGraphClient:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = messages
        self.calls: list[dict] = []

    def get_json(self, path: str, *, params: dict, headers: dict) -> dict:
        self.calls.append({"path": path, "params": params, "headers": headers})
        return {"value": self.messages}


def test_graph_message_maps_inbox_payload_to_common_schema() -> None:
    mail = graph_message_to_mail_input(_message("message-1"), folder_id="inbox")

    assert mail.mail_id == "OUTLOOK-message-1"
    assert mail.conversation_id == "OUTLOOK-CONVERSATION-conversation-1"
    assert mail.direction == MailDirection.INBOUND
    assert mail.sender == "requester@example.test"
    assert mail.recipients == ["worker@example.test", "observer@example.test"]
    assert mail.received_at is not None
    assert mail.sent_at is None
    assert mail.body == "합성 Outlook 업무를\n확인\n해 주세요."


def test_graph_message_maps_sent_items_to_outbound_schema() -> None:
    mail = graph_message_to_mail_input(
        _message("message-2", body="자료를 전달했습니다.", content_type="text"),
        folder_id="sentitems",
    )

    assert mail.direction == MailDirection.OUTBOUND
    assert mail.received_at is None
    assert mail.sent_at is not None
    assert mail.body == "자료를 전달했습니다."


def test_outlook_source_uses_readonly_message_list_contract_and_sorts() -> None:
    client = _FakeGraphClient(
        [
            _message("newer", received_at="2026-08-28T02:00:00Z"),
            _message("older", received_at="2026-08-28T01:00:00Z"),
        ]
    )
    source = OutlookGraphReadOnlySource(
        client,
        OutlookSourceSettings(folder_id="inbox", max_results=10),
    )

    mails = source.load()

    assert [mail.mail_id for mail in mails] == ["OUTLOOK-older", "OUTLOOK-newer"]
    assert client.calls == [
        {
            "path": "/me/mailFolders/inbox/messages",
            "params": {
                "$select": ",".join(GRAPH_MESSAGE_SELECT),
                "$top": 10,
                "$orderby": "receivedDateTime asc",
            },
            "headers": {"Prefer": 'outlook.body-content-type="text"'},
        }
    ]


def test_outlook_settings_restrict_folder_and_result_count(monkeypatch) -> None:
    monkeypatch.setenv("OUTLOOK_FOLDER_ID", "deleteditems")
    with pytest.raises(ValueError, match="inbox or sentitems"):
        load_outlook_source_settings()

    monkeypatch.setenv("OUTLOOK_FOLDER_ID", "inbox")
    monkeypatch.setenv("OUTLOOK_MAX_RESULTS", "101")
    with pytest.raises(ValueError, match="between 1 and 100"):
        load_outlook_source_settings()
