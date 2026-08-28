from __future__ import annotations

import json
from io import BytesIO

import pytest

from mailtaskagent.operations import SyncRunReport
from mailtaskagent.slack_notifications import (
    SlackNotificationSettings,
    build_attention_alert_payload,
    build_sync_alert_payload,
    load_slack_notification_settings,
    send_slack_payload,
)


class _Response(BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


def _report() -> SyncRunReport:
    return SyncRunReport(
        run_id="SYNC-TEST",
        source="GMAIL",
        status="PARTIAL",
        fetched_count=3,
        pending_count=2,
        succeeded_count=1,
        failed_count=1,
        duplicate_count=1,
        retry_count=1,
        failed_mail_ids=("GMAIL-secret-mail-id",),
        error_type="TimeoutError",
    )


def test_sync_alert_excludes_mail_ids_titles_and_secrets() -> None:
    payload = build_sync_alert_payload(_report())
    rendered = json.dumps(payload, ensure_ascii=False)

    assert "GMAIL-secret-mail-id" not in rendered
    assert "Task 제목" in rendered
    assert "api_key" not in rendered.casefold()
    assert "SYNC-TEST" in rendered


def test_attention_alert_contains_counts_not_task_details() -> None:
    payload = build_attention_alert_payload(
        {
            "active_task_count": 4,
            "pending_review_count": 2,
            "priority_counts": {"P1": 1, "P2": 2, "P3": 1, "P4": 0},
            "tasks": [{"title": "외부로 보내면 안 되는 업무 제목"}],
        }
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert "활성 업무 4건" in rendered
    assert "외부로 보내면 안 되는 업무 제목" not in rendered


def test_slack_sender_is_disabled_by_default() -> None:
    settings = SlackNotificationSettings(enabled=False, webhook_url="")

    assert send_slack_payload(settings, {"text": "test"}) == "DISABLED"


def test_slack_sender_posts_json_without_exposing_webhook() -> None:
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response(b"ok")

    settings = SlackNotificationSettings(
        enabled=True,
        webhook_url="https://hooks.slack.com/services/T/B/secret",
        timeout_seconds=3,
    )

    assert send_slack_payload(settings, {"text": "안전 알림"}, opener=opener) == "SENT"
    assert captured["body"] == {"text": "안전 알림"}
    assert captured["timeout"] == 3


def test_slack_sender_rejects_non_slack_webhook() -> None:
    settings = SlackNotificationSettings(
        enabled=True,
        webhook_url="https://example.test/services/T/B/secret",
    )

    with pytest.raises(ValueError, match="official HTTPS"):
        send_slack_payload(settings, {"text": "test"})


def test_slack_settings_loads_without_printing_secret(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv(
        "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/secret"
    )

    settings = load_slack_notification_settings()

    assert settings.enabled is True
    assert settings.configured is True
