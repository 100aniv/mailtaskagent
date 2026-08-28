from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import quote

from mailtaskagent.models import MailDirection, MailInput


GRAPH_MESSAGE_SELECT = (
    "id",
    "conversationId",
    "internetMessageId",
    "receivedDateTime",
    "sentDateTime",
    "from",
    "sender",
    "toRecipients",
    "ccRecipients",
    "bccRecipients",
    "subject",
    "body",
)
ALLOWED_GRAPH_FOLDERS = {"inbox", "sentitems"}


class GraphReadClient(Protocol):
    def get_json(
        self,
        path: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class OutlookSourceSettings:
    folder_id: str = "inbox"
    max_results: int = 25

    def __post_init__(self) -> None:
        normalized_folder = self.folder_id.strip().casefold()
        if normalized_folder not in ALLOWED_GRAPH_FOLDERS:
            raise ValueError("OUTLOOK_FOLDER_ID must be inbox or sentitems")
        if not 1 <= int(self.max_results) <= 100:
            raise ValueError("OUTLOOK_MAX_RESULTS must be between 1 and 100")
        object.__setattr__(self, "folder_id", normalized_folder)
        object.__setattr__(self, "max_results", int(self.max_results))


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return "\n".join(self.parts)


def load_outlook_source_settings() -> OutlookSourceSettings:
    return OutlookSourceSettings(
        folder_id=os.getenv("OUTLOOK_FOLDER_ID", "inbox"),
        max_results=int(os.getenv("OUTLOOK_MAX_RESULTS", "25")),
    )


def _parse_graph_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _address(recipient: dict[str, Any] | None) -> str:
    if not recipient:
        return ""
    return str(recipient.get("emailAddress", {}).get("address") or "").strip()


def _recipient_addresses(message: dict[str, Any]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for field in ("toRecipients", "ccRecipients", "bccRecipients"):
        for recipient in message.get(field, []) or []:
            address = _address(recipient)
            normalized = address.casefold()
            if address and normalized not in seen:
                seen.add(normalized)
                values.append(address)
    return values


def _body_text(body: dict[str, Any] | None) -> str:
    body = body or {}
    content = str(body.get("content") or "").strip()
    if str(body.get("contentType") or "").casefold() != "html":
        return content
    extractor = _HTMLTextExtractor()
    extractor.feed(content)
    return extractor.text().strip()


def graph_message_to_mail_input(
    message: dict[str, Any],
    *,
    folder_id: str = "inbox",
) -> MailInput:
    normalized_folder = folder_id.strip().casefold()
    if normalized_folder not in ALLOWED_GRAPH_FOLDERS:
        raise ValueError("Graph message folder must be inbox or sentitems")
    direction = (
        MailDirection.OUTBOUND
        if normalized_folder == "sentitems"
        else MailDirection.INBOUND
    )
    occurred_value = (
        message.get("sentDateTime")
        if direction == MailDirection.OUTBOUND
        else message.get("receivedDateTime")
    )
    if not occurred_value:
        raise ValueError("Graph message timestamp is required")
    occurred_at = _parse_graph_datetime(str(occurred_value))
    timestamp_fields = (
        {"sent_at": occurred_at}
        if direction == MailDirection.OUTBOUND
        else {"received_at": occurred_at}
    )
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        raise ValueError("Graph message id is required")
    conversation_id = str(message.get("conversationId") or message_id).strip()
    sender = _address(message.get("from")) or _address(message.get("sender"))
    return MailInput(
        mail_id=f"OUTLOOK-{message_id}",
        conversation_id=f"OUTLOOK-CONVERSATION-{conversation_id}",
        direction=direction,
        sender=sender,
        recipients=_recipient_addresses(message),
        subject=str(message.get("subject") or "").strip(),
        body=_body_text(message.get("body")),
        **timestamp_fields,
    )


class OutlookGraphReadOnlySource:
    def __init__(self, client: GraphReadClient, settings: OutlookSourceSettings) -> None:
        self.client = client
        self.settings = settings

    def load(self) -> list[MailInput]:
        folder_id = quote(self.settings.folder_id, safe="")
        response = self.client.get_json(
            f"/me/mailFolders/{folder_id}/messages",
            params={
                "$select": ",".join(GRAPH_MESSAGE_SELECT),
                "$top": self.settings.max_results,
                "$orderby": (
                    "sentDateTime asc"
                    if self.settings.folder_id == "sentitems"
                    else "receivedDateTime asc"
                ),
            },
            headers={"Prefer": 'outlook.body-content-type="text"'},
        )
        messages = [
            graph_message_to_mail_input(item, folder_id=self.settings.folder_id)
            for item in response.get("value", [])
        ]
        return sorted(messages, key=lambda mail: (mail.occurred_at, mail.mail_id))
