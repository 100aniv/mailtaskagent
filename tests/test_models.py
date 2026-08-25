from datetime import datetime

import pytest
from pydantic import ValidationError

from mailtaskagent.models import MailDirection, MailInput


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
