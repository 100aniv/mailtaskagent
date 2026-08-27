from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum


class PriorityLevel(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class PriorityRuleType(StrEnum):
    SENDER_EMAIL = "SENDER_EMAIL"
    SENDER_DOMAIN = "SENDER_DOMAIN"
    KEYWORD = "KEYWORD"


PRIORITY_PRESENTATION = {
    PriorityLevel.P1: ("🔴", "즉시 처리"),
    PriorityLevel.P2: ("🟠", "우선 처리"),
    PriorityLevel.P3: ("🔵", "예정 업무"),
    PriorityLevel.P4: ("⚪", "일반 업무"),
}


@dataclass(frozen=True)
class PriorityDecision:
    level: PriorityLevel
    importance: int
    urgency: int
    reasons: tuple[str, ...]

    @property
    def emoji(self) -> str:
        return PRIORITY_PRESENTATION[self.level][0]

    @property
    def label(self) -> str:
        return PRIORITY_PRESENTATION[self.level][1]

    @property
    def display(self) -> str:
        return f"{self.emoji} {self.label}"

    @property
    def reason(self) -> str:
        return " · ".join(self.reasons) if self.reasons else "기본 우선순위"


DEFAULT_PRIORITY_SETTINGS = {
    "due_soon_days": 3,
    "due_later_days": 7,
    "waiting_attention_days": 3,
}


def _days_waiting(value: str | None, now: datetime) -> int | None:
    if not value:
        return None
    started = datetime.fromisoformat(value)
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return max(0, (now - started.astimezone(UTC)).days)


def _rule_matches(rule: dict, task: dict) -> bool:
    pattern = str(rule.get("pattern") or "").strip().casefold()
    if not pattern:
        return False
    requester = str(task.get("requester") or "").strip().casefold()
    text = " ".join(
        str(task.get(field) or "") for field in ("title", "description", "requester")
    ).casefold()
    rule_type = PriorityRuleType(rule["rule_type"])
    if rule_type == PriorityRuleType.SENDER_EMAIL:
        return requester == pattern
    if rule_type == PriorityRuleType.SENDER_DOMAIN:
        domain = pattern.removeprefix("@")
        return requester.endswith(f"@{domain}")
    return pattern in text


def calculate_task_priority(
    task: dict,
    rules: list[dict] | None = None,
    settings: dict[str, int] | None = None,
    *,
    today: date | None = None,
    now: datetime | None = None,
) -> PriorityDecision:
    today = today or date.today()
    now = now or datetime.now(UTC)
    resolved_settings = {**DEFAULT_PRIORITY_SETTINGS, **(settings or {})}
    reasons: list[str] = []

    importance_override = task.get("importance_override")
    if importance_override is not None:
        importance = int(importance_override)
        reasons.append(f"사용자 중요도 P{importance}")
    else:
        importance = 4
        for rule in rules or []:
            if not bool(rule.get("enabled", True)) or not _rule_matches(rule, task):
                continue
            rule_importance = int(rule["importance"])
            if rule_importance < importance:
                importance = rule_importance
            reasons.append(
                f"{rule.get('name') or rule['rule_type']} Rule P{rule_importance}"
            )

    urgency = 4
    due_value = task.get("due_date")
    if due_value:
        due = date.fromisoformat(str(due_value))
        days = (due - today).days
        if days < 0:
            urgency = 1
            reasons.append(f"기한 {abs(days)}일 초과")
        elif days == 0:
            urgency = 1
            reasons.append("오늘 기한")
        elif days <= int(resolved_settings["due_soon_days"]):
            urgency = 2
            reasons.append(f"기한 {days}일 남음")
        elif days <= int(resolved_settings["due_later_days"]):
            urgency = 3
            reasons.append(f"기한 {days}일 남음")

    waiting_days = _days_waiting(task.get("waiting_since"), now)
    if waiting_days is not None and waiting_days >= int(
        resolved_settings["waiting_attention_days"]
    ):
        urgency = min(urgency, 2)
        reasons.append(f"회신 {waiting_days}일 대기")

    if urgency == 1 or (importance == 1 and urgency <= 2):
        level = PriorityLevel.P1
    elif importance <= 2 or urgency == 2:
        level = PriorityLevel.P2
    elif importance == 3 or urgency == 3:
        level = PriorityLevel.P3
    else:
        level = PriorityLevel.P4

    return PriorityDecision(
        level=level,
        importance=importance,
        urgency=urgency,
        reasons=tuple(reasons),
    )
