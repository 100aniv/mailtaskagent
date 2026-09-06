from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol

from mailtaskagent.gmail_source import (
    EMAIL_ADDRESS_PATTERN,
    GMAIL_CONVERSATION_PREFIX,
    build_gmail_service,
    load_gmail_source_settings,
)


GMAIL_MAIL_PREFIX = "GMAIL-"


@dataclass(frozen=True)
class GmailApprovedSendSettings:
    enabled: bool
    allowed_recipients: tuple[str, ...]

    def recipient_allowed(self, recipient: str) -> bool:
        return recipient.casefold() in {
            item.casefold() for item in self.allowed_recipients
        }


@dataclass(frozen=True)
class GmailSendResult:
    message_id: str
    thread_id: str
    sender: str


class ReplySender(Protocol):
    def send_reply(
        self,
        *,
        source_message_id: str,
        thread_id: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> GmailSendResult: ...


def load_gmail_approved_send_settings() -> GmailApprovedSendSettings:
    enabled = os.getenv("GMAIL_APPROVED_SEND_ENABLED", "false").strip().casefold()
    recipients = tuple(
        item.strip()
        for item in os.getenv("GMAIL_SEND_ALLOWED_RECIPIENTS", "").split(",")
        if item.strip()
    )
    invalid = [
        item for item in recipients if EMAIL_ADDRESS_PATTERN.fullmatch(item) is None
    ]
    if invalid:
        raise ValueError("GMAIL_SEND_ALLOWED_RECIPIENTS contains an invalid email address")
    return GmailApprovedSendSettings(
        enabled=enabled in {"1", "true", "yes", "on"},
        allowed_recipients=recipients,
    )


def build_gmail_reply_sender() -> "GmailReplySender":
    source_settings = load_gmail_source_settings()
    service = build_gmail_service(
        source_settings,
        allow_interactive_auth=False,
        include_send_scope=True,
    )
    return GmailReplySender(service)


def gmail_send_idempotency_key(
    *, reply_id: int, source_mail_id: str, recipient: str, body: str
) -> str:
    value = f"{reply_id}\n{source_mail_id}\n{recipient.casefold()}\n{body}".encode()
    return hashlib.sha256(value).hexdigest()


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {
        item.get("name", "").casefold(): item.get("value", "").strip()
        for item in message.get("payload", {}).get("headers", [])
    }


def gmail_reply_subject(subject: str) -> str:
    clean = subject.strip()
    return clean if clean.casefold().startswith("re:") else f"Re: {clean}"


class GmailReplySender:
    def __init__(self, service: Any) -> None:
        self.service = service

    def send_reply(
        self,
        *,
        source_message_id: str,
        thread_id: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> GmailSendResult:
        if EMAIL_ADDRESS_PATTERN.fullmatch(recipient) is None:
            raise ValueError("Reply recipient is not a valid email address")
        original = (
            self.service.users()
            .messages()
            .get(
                userId="me",
                id=source_message_id,
                format="metadata",
                metadataHeaders=["Message-ID", "References", "Subject"],
            )
            .execute()
        )
        if original.get("threadId") != thread_id:
            raise ValueError("Source message does not belong to the expected Gmail thread")
        headers = _headers(original)
        message_id = headers.get("message-id")
        if not message_id:
            raise ValueError("Source Gmail message is missing Message-ID")

        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = gmail_reply_subject(headers.get("subject") or subject)
        message["In-Reply-To"] = message_id
        references = headers.get("references", "").strip()
        message["References"] = f"{references} {message_id}".strip()
        message.set_content(body.strip())
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

        profile = self.service.users().getProfile(userId="me").execute()
        sender = str(profile.get("emailAddress") or "").strip()
        if EMAIL_ADDRESS_PATTERN.fullmatch(sender) is None:
            raise ValueError("Gmail profile did not return a valid sender address")

        sent = (
            self.service.users()
            .messages()
            .send(userId="me", body={"raw": raw, "threadId": thread_id})
            .execute()
        )
        sent_message_id = str(sent.get("id") or "").strip()
        sent_thread_id = str(sent.get("threadId") or "").strip()
        if not sent_message_id or sent_thread_id != thread_id:
            raise ValueError("Gmail send response is missing the expected message or thread ID")
        return GmailSendResult(
            message_id=sent_message_id,
            thread_id=sent_thread_id,
            sender=sender,
        )


def source_gmail_ids(source_mail_id: str, conversation_id: str) -> tuple[str, str]:
    if not source_mail_id.startswith(GMAIL_MAIL_PREFIX):
        raise ValueError("Only a Gmail source mail can be replied to")
    if not conversation_id.startswith(GMAIL_CONVERSATION_PREFIX):
        raise ValueError("Only a Gmail thread can be replied to")
    message_id = source_mail_id.removeprefix(GMAIL_MAIL_PREFIX).strip()
    thread_id = conversation_id.removeprefix(GMAIL_CONVERSATION_PREFIX).strip()
    if not message_id or not thread_id:
        raise ValueError("Gmail message or thread ID is missing")
    return message_id, thread_id
