from __future__ import annotations

from enum import StrEnum
from typing import Any

from mailtaskagent.config import Settings
from mailtaskagent.llm_client import MailAnalyzer, build_analyzer
from mailtaskagent.models import MailAnalysis, MailInput, MailIntent


class MailFilterRuleType(StrEnum):
    SENDER_EMAIL = "SENDER_EMAIL"
    SENDER_DOMAIN = "SENDER_DOMAIN"
    SUBJECT_KEYWORD = "SUBJECT_KEYWORD"


def match_mail_filter_rule(mail: MailInput, rules: list[dict]) -> dict | None:
    sender = mail.sender.strip().casefold()
    subject = mail.subject.strip().casefold()
    for rule in rules:
        if not bool(rule.get("enabled", True)):
            continue
        pattern = str(rule.get("pattern") or "").strip().casefold()
        if not pattern:
            continue
        rule_type = MailFilterRuleType(rule["rule_type"])
        if rule_type == MailFilterRuleType.SENDER_EMAIL:
            matched = sender == pattern
        elif rule_type == MailFilterRuleType.SENDER_DOMAIN:
            matched = sender.endswith(f"@{pattern.removeprefix('@')}")
        else:
            matched = pattern in subject
        if matched:
            return rule
    return None


class RuleAwareMailAnalyzer:
    def __init__(self, delegate: MailAnalyzer, storage: Any) -> None:
        self.delegate = delegate
        self.storage = storage
        self.last_analysis_source = "DELEGATE"

    def analyze(self, mail: MailInput) -> MailAnalysis:
        rule = match_mail_filter_rule(mail, self.storage.list_mail_filter_rules())
        if rule is None:
            self.last_analysis_source = "DELEGATE"
            return self.delegate.analyze(mail)
        self.last_analysis_source = "USER_FILTER_RULE"
        return MailAnalysis(
            is_task_request=False,
            intent=MailIntent.NON_TASK,
            requester=mail.sender,
            reason=(
                f"사용자 제외 Rule '{rule['name']}' 적용 "
                f"({rule['rule_type']}: {rule['pattern']})"
            ),
            confidence=1.0,
        )


def build_operational_analyzer(settings: Settings, storage: Any) -> RuleAwareMailAnalyzer:
    return RuleAwareMailAnalyzer(build_analyzer(settings), storage)
