from __future__ import annotations

import base64
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from mailtaskagent.config import PROJECT_ROOT
from mailtaskagent.models import MailDirection, MailInput


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
DEFAULT_GMAIL_QUERY = "label:MailTaskAgent-Demo"
GMAIL_CONVERSATION_PREFIX = "GMAIL-THREAD-"
MAX_TRACKED_GMAIL_THREADS = 100
EMAIL_ADDRESS_PATTERN = re.compile(
    r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+",
    re.IGNORECASE,
)
GMAIL_QUOTE_MARKERS = (
    re.compile(r"^On .+ wrote:$", re.IGNORECASE),
    re.compile(r"^20\d{2}년 .+님이 작성:$"),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}$", re.IGNORECASE),
)


@dataclass(frozen=True)
class GmailSourceSettings:
    credentials_path: Path
    token_path: Path
    query: str = DEFAULT_GMAIL_QUERY
    max_results: int = 25


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


def _resolve_project_path(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_gmail_source_settings() -> GmailSourceSettings:
    query = os.getenv("GMAIL_QUERY", DEFAULT_GMAIL_QUERY).strip()
    if not query:
        raise ValueError("GMAIL_QUERY must restrict the test mailbox input")
    max_results = int(os.getenv("GMAIL_MAX_RESULTS", "25"))
    if not 1 <= max_results <= 100:
        raise ValueError("GMAIL_MAX_RESULTS must be between 1 and 100")
    return GmailSourceSettings(
        credentials_path=_resolve_project_path(
            os.getenv("GMAIL_CREDENTIALS_PATH", ".secrets/gmail_credentials.json")
        ),
        token_path=_resolve_project_path(
            os.getenv("GMAIL_TOKEN_PATH", ".secrets/gmail_token.json")
        ),
        query=query,
        max_results=max_results,
    )


def build_gmail_service(settings: GmailSourceSettings) -> Any:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError(
            "Gmail dependencies are missing. Install requirements-gmail.txt first."
        ) from error

    if not settings.credentials_path.exists():
        raise FileNotFoundError(
            f"Gmail OAuth desktop credentials were not found: {settings.credentials_path}"
        )

    credentials = None
    if settings.token_path.exists():
        credentials = Credentials.from_authorized_user_file(
            str(settings.token_path), [GMAIL_READONLY_SCOPE]
        )
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(settings.credentials_path), [GMAIL_READONLY_SCOPE]
            )
            credentials = flow.run_local_server(port=0)
        settings.token_path.parent.mkdir(parents=True, exist_ok=True)
        settings.token_path.write_text(credentials.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _decode_header(raw_value: str) -> str:
    values = []
    for value, encoding in decode_header(raw_value):
        if isinstance(value, bytes):
            values.append(value.decode(encoding or "utf-8", errors="replace"))
        else:
            values.append(value)
    return "".join(values).strip()


def _decode_body(data: str | None) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace").strip()


def _extract_addresses(raw_values: list[str]) -> list[str]:
    parsed = [address for _, address in getaddresses(raw_values) if address]
    extracted = EMAIL_ADDRESS_PATTERN.findall(", ".join(raw_values))
    unique: list[str] = []
    seen: set[str] = set()
    for address in [*parsed, *extracted]:
        normalized = address.casefold()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(address)
    return unique


def _strip_quoted_reply(text: str) -> str:
    """Keep only the newly written reply and discard quoted thread history."""

    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(pattern.match(stripped) for pattern in GMAIL_QUOTE_MARKERS):
            break
        if stripped.startswith(">"):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _extract_body(payload: dict[str, Any]) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def visit(part: dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        content = _decode_body(part.get("body", {}).get("data"))
        if mime_type == "text/plain" and content:
            plain_parts.append(content)
        elif mime_type == "text/html" and content:
            html_parts.append(content)
        for child in part.get("parts", []):
            visit(child)

    visit(payload)
    if plain_parts:
        return _strip_quoted_reply("\n\n".join(plain_parts))
    if html_parts:
        extractor = _HTMLTextExtractor()
        extractor.feed("\n".join(html_parts))
        return _strip_quoted_reply(extractor.text())
    return ""


def gmail_message_to_mail_input(message: dict[str, Any]) -> MailInput:
    payload = message.get("payload", {})
    headers = {
        item.get("name", "").casefold(): _decode_header(item.get("value", ""))
        for item in payload.get("headers", [])
    }
    raw_sender = headers.get("from", "")
    sender_addresses = _extract_addresses([raw_sender])
    sender = (
        sender_addresses[0]
        if sender_addresses
        else parseaddr(raw_sender)[1] or raw_sender
    )
    recipient_headers = [
        headers.get("to", ""),
        headers.get("cc", ""),
        headers.get("bcc", ""),
    ]
    recipients = _extract_addresses(recipient_headers)
    direction = (
        MailDirection.OUTBOUND
        if "SENT" in set(message.get("labelIds", []))
        else MailDirection.INBOUND
    )
    occurred_at = datetime.fromtimestamp(
        int(message["internalDate"]) / 1000,
        tz=timezone.utc,
    )
    timestamp_fields = (
        {"sent_at": occurred_at}
        if direction == MailDirection.OUTBOUND
        else {"received_at": occurred_at}
    )
    return MailInput(
        mail_id=f"GMAIL-{message['id']}",
        conversation_id=f"{GMAIL_CONVERSATION_PREFIX}{message['threadId']}",
        direction=direction,
        sender=sender,
        recipients=recipients,
        subject=headers.get("subject", ""),
        body=_extract_body(payload),
        **timestamp_fields,
    )


class GmailReadOnlySource:
    def __init__(
        self,
        service: Any,
        settings: GmailSourceSettings,
        *,
        tracked_conversation_ids: Iterable[str] = (),
    ) -> None:
        self.service = service
        self.settings = settings
        self.tracked_thread_ids = self._normalize_tracked_thread_ids(
            tracked_conversation_ids
        )
        self.missing_thread_count = 0

    @staticmethod
    def _normalize_tracked_thread_ids(
        conversation_ids: Iterable[str],
    ) -> tuple[str, ...]:
        thread_ids: list[str] = []
        seen: set[str] = set()
        for conversation_id in conversation_ids:
            if not conversation_id.startswith(GMAIL_CONVERSATION_PREFIX):
                continue
            thread_id = conversation_id.removeprefix(GMAIL_CONVERSATION_PREFIX).strip()
            if not thread_id or thread_id in seen:
                continue
            seen.add(thread_id)
            thread_ids.append(thread_id)
            if len(thread_ids) >= MAX_TRACKED_GMAIL_THREADS:
                break
        return tuple(thread_ids)

    def load(self) -> list[MailInput]:
        response = (
            self.service.users()
            .messages()
            .list(
                userId="me",
                q=self.settings.query,
                maxResults=self.settings.max_results,
                includeSpamTrash=False,
            )
            .execute()
        )
        raw_messages: dict[str, dict[str, Any]] = {}
        for item in response.get("messages", []):
            raw_message = (
                self.service.users()
                .messages()
                .get(userId="me", id=item["id"], format="full")
                .execute()
            )
            raw_messages[raw_message["id"]] = raw_message

        # The restricted label is the safe entry gate for new work. Once a Gmail
        # conversation has created or linked a Task, follow that exact thread so
        # later Inbox and Sent messages remain part of the same lifecycle even if
        # an individual reply does not inherit the entry label.
        for thread_id in self.tracked_thread_ids:
            try:
                thread = (
                    self.service.users()
                    .threads()
                    .get(userId="me", id=thread_id, format="full")
                    .execute()
                )
            except Exception as exc:
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status not in {404, 410}:
                    raise
                self.missing_thread_count += 1
                continue
            for raw_message in thread.get("messages", []):
                raw_messages[raw_message["id"]] = raw_message

        messages = [
            gmail_message_to_mail_input(raw_message)
            for raw_message in raw_messages.values()
        ]
        return sorted(messages, key=lambda mail: (mail.occurred_at, mail.mail_id))
