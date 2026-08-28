from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from mailtaskagent.operations import SyncRunReport


@dataclass(frozen=True)
class SlackNotificationSettings:
    enabled: bool
    webhook_url: str
    timeout_seconds: float = 5.0

    @property
    def configured(self) -> bool:
        return bool(self.webhook_url)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def load_slack_notification_settings() -> SlackNotificationSettings:
    return SlackNotificationSettings(
        enabled=_as_bool(os.getenv("SLACK_NOTIFICATIONS_ENABLED")),
        webhook_url=os.getenv("SLACK_WEBHOOK_URL", "").strip(),
        timeout_seconds=max(
            1.0,
            min(30.0, float(os.getenv("SLACK_NOTIFICATION_TIMEOUT_SECONDS", "5"))),
        ),
    )


def _validate_webhook_url(webhook_url: str) -> None:
    parsed = urlparse(webhook_url)
    allowed_hosts = {"hooks.slack.com", "hooks.slack-gov.com"}
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or not parsed.path.startswith("/services/")
    ):
        raise ValueError("Slack webhook URL must be an official HTTPS incoming webhook")


def build_sync_alert_payload(report: SyncRunReport) -> dict:
    status_label = {
        "FAILED": "실패",
        "PARTIAL": "일부 실패",
        "SUCCESS": "정상",
    }.get(report.status, report.status)
    summary = (
        f"Gmail 자동 정리 {status_label} · 성공 {report.succeeded_count}건 · "
        f"실패 {report.failed_count}건"
    )
    fields = [
        {"type": "mrkdwn", "text": f"*실행 ID*\n{report.run_id}"},
        {"type": "mrkdwn", "text": f"*오류 종류*\n{report.error_type or '-'}"},
        {"type": "mrkdwn", "text": f"*가져옴 / 신규*\n{report.fetched_count} / {report.pending_count}"},
        {"type": "mrkdwn", "text": f"*중복 / 재시도*\n{report.duplicate_count} / {report.retry_count}"},
    ]
    return {
        "text": f"MailTaskAgent: {summary}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "MailTaskAgent 확인 필요"},
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
            {"type": "section", "fields": fields},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "메일 원문·Task 제목·인증정보는 알림에 포함하지 않습니다.",
                    }
                ],
            },
        ],
    }


def build_attention_alert_payload(snapshot: dict) -> dict:
    counts = snapshot.get("priority_counts") or {}
    active_count = int(snapshot.get("active_task_count") or 0)
    review_count = int(snapshot.get("pending_review_count") or 0)
    summary = (
        f"활성 업무 {active_count}건 · P1 {int(counts.get('P1') or 0)}건 · "
        f"사용자 검토 {review_count}건"
    )
    return {
        "text": f"MailTaskAgent: {summary}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "MailTaskAgent 업무 확인"},
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "상세 업무와 판단 근거는 로컬 Dashboard에서 확인하세요.",
                    }
                ],
            },
        ],
    }


def send_slack_payload(
    settings: SlackNotificationSettings,
    payload: dict,
    *,
    opener: Callable = urlopen,
) -> str:
    if not settings.enabled:
        return "DISABLED"
    if not settings.configured:
        return "NOT_CONFIGURED"
    _validate_webhook_url(settings.webhook_url)
    request = Request(
        settings.webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with opener(request, timeout=settings.timeout_seconds) as response:
        if getattr(response, "status", 200) != 200:
            raise RuntimeError("Slack webhook returned a non-success status")
        body = response.read().decode("utf-8", errors="replace").strip()
        if body != "ok":
            raise RuntimeError("Slack webhook did not acknowledge the message")
    return "SENT"
