from __future__ import annotations

from datetime import datetime

from mailtaskagent.models import (
    MailDirection,
    MailInput,
    ReplyAction,
    ReplyPlan,
)
from mailtaskagent.reply_assistant import ReplyAssistant
from mailtaskagent.storage import SQLiteStorage


INPUT_REQUIRED_ACTIONS = {
    ReplyAction.DATE_REPLY,
    ReplyAction.VALUE_REPLY,
    ReplyAction.APPROVE_REPLY,
}


def _stored_mail_to_input(row: dict) -> MailInput:
    direction = MailDirection(row["direction"])
    occurred_at = datetime.fromisoformat(row["occurred_at"])
    timestamp = (
        {"received_at": occurred_at}
        if direction == MailDirection.INBOUND
        else {"sent_at": occurred_at}
    )
    return MailInput(
        mail_id=row["mail_id"],
        conversation_id=row["conversation_id"],
        direction=direction,
        sender=row["sender"],
        recipients=row.get("recipients") or [],
        subject=row["subject"],
        body=row["body"],
        **timestamp,
    )


class MailToActionDraftService:
    """Plan and persist reply drafts without sending or changing the Task."""

    def __init__(
        self,
        storage: SQLiteStorage,
        assistant: ReplyAssistant,
        *,
        confidence_threshold: float = 0.75,
    ) -> None:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("Reply confidence threshold must be between 0 and 1")
        self.storage = storage
        self.assistant = assistant
        self.confidence_threshold = confidence_threshold

    def _task_context_and_mail(self, task_id: str, source_mail_id: str | None = None):
        context = self.storage.get_task_context(task_id, history_limit=5)
        if context is None:
            raise ValueError(f"Task not found: {task_id}")
        rows = self.storage.list_thread_mails(
            context["task"]["conversation_id"], limit=20
        )
        if source_mail_id:
            row = next((item for item in rows if item["mail_id"] == source_mail_id), None)
        else:
            row = next(
                (item for item in rows if item["direction"] == MailDirection.INBOUND.value),
                None,
            )
        if row is None:
            raise ValueError("This Task has no inbound mail available for a reply")
        return context, _stored_mail_to_input(row)

    def prepare(self, task_id: str) -> dict:
        context, mail = self._task_context_and_mail(task_id)
        try:
            plan = self.assistant.plan(mail, context)
        except Exception:
            plan = ReplyPlan(
                action=ReplyAction.ASK_USER,
                confidence=0,
                reason="Reply Agent 호출 또는 Schema 검증 실패로 자동 초안 생성을 중지함",
                question="메일 내용을 확인하고 직접 회신 방향을 결정해 주세요.",
            )
        if plan.confidence < self.confidence_threshold and plan.action != ReplyAction.ASK_USER:
            plan = ReplyPlan(
                action=ReplyAction.ASK_USER,
                confidence=plan.confidence,
                reason=f"Reply Agent 신뢰도 기준 미달: {plan.reason}",
                question="메일 내용을 확인하고 직접 회신 방향을 결정해 주세요.",
            )
        return self.storage.create_reply_plan(
            task_id=task_id,
            source_mail_id=mail.mail_id,
            reply_action=plan.action.value,
            question=plan.question,
            draft_body=plan.draft_body,
            reason=plan.reason,
            confidence=plan.confidence,
        )

    def compose(self, reply_id: int, user_input: str) -> dict:
        record = self.storage.get_reply_draft(reply_id)
        if record is None:
            raise ValueError(f"Reply draft not found: {reply_id}")
        action = ReplyAction(record["reply_action"])
        if action not in INPUT_REQUIRED_ACTIONS:
            raise ValueError(f"{action.value} does not accept structured user input")
        context, mail = self._task_context_and_mail(
            record["task_id"], record["source_mail_id"]
        )
        plan = ReplyPlan(
            action=action,
            confidence=record["confidence"],
            reason=record["reason"],
            question=record["question"],
        )
        try:
            draft = self.assistant.compose(mail, context, plan, user_input)
        except Exception as exc:
            raise ValueError(
                "Reply Agent 호출 또는 Schema 검증 실패로 초안 생성을 중지했습니다."
            ) from exc
        if draft.action != action:
            raise ValueError("Reply Agent changed the approved reply action")
        return self.storage.update_reply_draft(
            reply_id,
            draft_body=draft.body,
            user_input=draft.user_input,
        )

    def save_user_edit(self, reply_id: int, draft_body: str) -> dict:
        record = self.storage.get_reply_draft(reply_id)
        if record is None:
            raise ValueError(f"Reply draft not found: {reply_id}")
        if record["status"] != "DRAFTED":
            raise ValueError("Only a generated draft can be edited")
        return self.storage.update_reply_draft(
            reply_id,
            draft_body=draft_body,
            user_input=record.get("user_input"),
            user_edited=True,
        )
