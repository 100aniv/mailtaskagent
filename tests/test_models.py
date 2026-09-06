from datetime import datetime

import pytest
from pydantic import ValidationError

from mailtaskagent.models import MailDirection, MailInput, ReplyAction, ReplyPlan


def test_outbound_mail_uses_sent_at_as_occurred_at() -> None:
    mail = MailInput(
        mail_id="M-OUT",
        conversation_id="T-1",
        direction=MailDirection.OUTBOUND,
        sender="user@example.test",
        recipients=["a@example.test"],
        sent_at="2026-08-25T09:00:00+09:00",
        subject="자료 요청",
        body="자료를 보내 주세요.",
    )
    assert mail.occurred_at == datetime.fromisoformat("2026-08-25T09:00:00+09:00")


def test_inbound_mail_requires_received_at() -> None:
    with pytest.raises(ValidationError):
        MailInput(
            mail_id="M-IN",
            conversation_id="T-1",
            direction=MailDirection.INBOUND,
            sender="a@example.test",
            subject="요청",
            body="확인해 주세요.",
        )


def test_reply_plan_requires_question_for_structured_input() -> None:
    with pytest.raises(ValidationError):
        ReplyPlan(
            action=ReplyAction.DATE_REPLY,
            confidence=0.9,
            reason="날짜 필요",
        )


def test_no_reply_cannot_contain_a_draft() -> None:
    with pytest.raises(ValidationError):
        ReplyPlan(
            action=ReplyAction.NO_REPLY,
            confidence=0.9,
            reason="회신 불필요",
            draft_body="발송하면 안 되는 문장",
        )
