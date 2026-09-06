from __future__ import annotations

from datetime import UTC, datetime

from mailtaskagent.gmail_send import (
    GmailApprovedSendSettings,
    ReplySender,
    gmail_reply_subject,
    gmail_send_idempotency_key,
    source_gmail_ids,
)
from mailtaskagent.models import MailDirection, MailInput, TaskStatus
from mailtaskagent.policy import validate_status_transition
from mailtaskagent.storage import SQLiteStorage


class GmailApprovedSendService:
    """Send one approved Gmail reply and observe the resulting Task state."""

    def __init__(
        self,
        storage: SQLiteStorage,
        sender: ReplySender | None,
        settings: GmailApprovedSendSettings,
    ) -> None:
        self.storage = storage
        self.sender = sender
        self.settings = settings

    def _event(
        self,
        *,
        reply_id: int,
        mail_id: str,
        step: str,
        status: str,
        message: str,
        details: dict | None = None,
        level: str = "INFO",
    ) -> None:
        self.storage.append_event(
            case_id=f"GMAIL-SEND-{reply_id}",
            mail_id=mail_id,
            step=step,
            status=status,
            message=message,
            details=details,
            level=level,
        )

    def preview(self, reply_id: int) -> dict:
        if not self.settings.enabled:
            raise ValueError("Gmail 사용자 승인 발송 기능이 비활성화되어 있습니다")
        draft = self.storage.get_reply_draft(reply_id)
        if draft is None:
            raise ValueError(f"Reply draft not found: {reply_id}")
        if self.storage.get_reply_send(reply_id) is not None:
            raise ValueError("이 회신 초안은 이미 발송을 시도했습니다")
        if draft["status"] != "DRAFTED" or not str(
            draft.get("draft_body") or ""
        ).strip():
            raise ValueError("완성된 회신 초안만 발송할 수 있습니다")
        task = self.storage.get_task(draft["task_id"])
        if task is None:
            raise ValueError(f"Task not found: {draft['task_id']}")
        validate_status_transition(task["status"], TaskStatus.WAITING_REPLY)
        mails = self.storage.list_thread_mails(task["conversation_id"], limit=100)
        source = next(
            (item for item in mails if item["mail_id"] == draft["source_mail_id"]),
            None,
        )
        if source is None or source["direction"] != MailDirection.INBOUND.value:
            raise ValueError("원본 Gmail 수신 Mail을 확인할 수 없습니다")
        recipient = str(source["sender"] or "").strip()
        if not self.settings.recipient_allowed(recipient):
            raise ValueError("원본 발신자가 테스트 수신자 Allowlist에 없습니다")
        source_message_id, thread_id = source_gmail_ids(
            source["mail_id"], source["conversation_id"]
        )
        return {
            "reply_id": reply_id,
            "task_id": task["task_id"],
            "source_mail_id": source["mail_id"],
            "source_message_id": source_message_id,
            "thread_id": thread_id,
            "recipient": recipient,
            "subject": gmail_reply_subject(source["subject"]),
            "body": draft["draft_body"],
            "task_status": task["status"],
        }

    def send(self, reply_id: int, *, user_confirmed: bool) -> dict:
        if not user_confirmed:
            raise ValueError("사용자가 Gmail 발송을 명시적으로 승인해야 합니다")
        preview = self.preview(reply_id)
        if self.sender is None:
            raise ValueError("Gmail 발송 Adapter가 준비되지 않았습니다")
        key = gmail_send_idempotency_key(
            reply_id=reply_id,
            source_mail_id=preview["source_mail_id"],
            recipient=preview["recipient"],
            body=preview["body"],
        )
        reservation = self.storage.reserve_reply_send(
            reply_id=reply_id,
            recipient=preview["recipient"],
            gmail_thread_id=preview["thread_id"],
            idempotency_key=key,
        )
        self._event(
            reply_id=reply_id,
            mail_id=preview["source_mail_id"],
            step="GMAIL_SEND_GUARD",
            status="ACCEPTED",
            message="사용자 승인·수신자 Allowlist·Task 상태·중복 발송 검증 통과",
            details={
                "reply_id": reply_id,
                "task_id": preview["task_id"],
                "thread_locked": True,
                "recipient_allowlisted": True,
                "user_confirmed": True,
            },
        )
        try:
            result = self.sender.send_reply(
                source_message_id=preview["source_message_id"],
                thread_id=preview["thread_id"],
                recipient=preview["recipient"],
                subject=preview["subject"],
                body=preview["body"],
            )
        except Exception as exc:
            self.storage.fail_reply_send(
                reservation["send_id"], error_type=type(exc).__name__
            )
            self._event(
                reply_id=reply_id,
                mail_id=preview["source_mail_id"],
                step="GMAIL_SEND_EXECUTION",
                status="FAILED",
                message="Gmail 발송 결과를 확정하지 못해 자동 재발송을 차단",
                details={
                    "send_id": reservation["send_id"],
                    "error_type": type(exc).__name__,
                    "automatic_retry": False,
                },
                level="ERROR",
            )
            raise ValueError(
                "Gmail 발송 결과를 확인할 수 없습니다. 자동 재발송하지 말고 보낸편지함을 확인하세요."
            ) from exc

        self._event(
            reply_id=reply_id,
            mail_id=preview["source_mail_id"],
            step="GMAIL_SEND_EXECUTION",
            status="SUCCESS",
            message="Gmail API가 사용자 승인 회신을 동일 Thread에 저장",
            details={
                "send_id": reservation["send_id"],
                "gmail_message_id": f"GMAIL-{result.message_id}",
                "gmail_thread_id": result.thread_id,
                "automatic_retry": False,
            },
        )

        outbound_mail = MailInput(
            mail_id=f"GMAIL-{result.message_id}",
            conversation_id=f"GMAIL-THREAD-{result.thread_id}",
            direction=MailDirection.OUTBOUND,
            sender=result.sender,
            recipients=[preview["recipient"]],
            sent_at=datetime.now(UTC),
            subject=preview["subject"],
            body=preview["body"],
        )
        try:
            completed = self.storage.complete_reply_send(
                reservation["send_id"], outbound_mail
            )
        except Exception as exc:
            self._event(
                reply_id=reply_id,
                mail_id=preview["source_mail_id"],
                step="GMAIL_SEND_OBSERVATION",
                status="UNKNOWN",
                message="Gmail은 응답했지만 로컬 저장 결과를 확정하지 못함",
                details={
                    "send_id": reservation["send_id"],
                    "error_type": type(exc).__name__,
                    "automatic_retry": False,
                },
                level="ERROR",
            )
            raise ValueError(
                "메일이 발송되었을 수 있으나 로컬 반영에 실패했습니다. 보낸편지함을 확인하세요."
            ) from exc
        self._event(
            reply_id=reply_id,
            mail_id=outbound_mail.mail_id,
            step="GMAIL_SEND_OBSERVATION",
            status="SUCCESS",
            message="Gmail 발송 성공과 Task 회신 대기 전환 확인",
            details={
                "send_id": reservation["send_id"],
                "gmail_message_id": outbound_mail.mail_id,
                "task_id": preview["task_id"],
                "task_status": completed["task"]["status"],
                "mail_sent": True,
            },
        )
        return completed
