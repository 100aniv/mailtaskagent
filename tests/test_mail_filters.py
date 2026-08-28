from __future__ import annotations

from pathlib import Path

from mailtaskagent.config import PROJECT_ROOT, Settings
from mailtaskagent.llm_client import MockMailAnalyzer
from mailtaskagent.mail_filters import (
    RuleAwareMailAnalyzer,
    match_mail_filter_rule,
)
from mailtaskagent.models import AgentAction, MailDirection, MailInput
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow, load_mails


def _mail(*, subject: str = "뉴스레터", body: str = "일반 본문") -> MailInput:
    return MailInput(
        mail_id="FILTER-001",
        conversation_id="FILTER-THREAD-001",
        direction=MailDirection.INBOUND,
        sender="newsletter@example.test",
        recipients=["worker@example.test"],
        received_at="2026-08-28T09:00:00+09:00",
        subject=subject,
        body=body,
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=tmp_path / "mail-filter.db",
        confidence_threshold=0.75,
    )


def test_mail_filter_matches_sender_domain_and_subject_but_not_body() -> None:
    mail = _mail(subject="8월 제품 뉴스레터", body="본문에 비밀키워드가 있습니다")

    assert match_mail_filter_rule(
        mail,
        [{"rule_type": "SENDER_EMAIL", "pattern": "newsletter@example.test"}],
    )
    assert match_mail_filter_rule(
        mail,
        [{"rule_type": "SENDER_DOMAIN", "pattern": "example.test"}],
    )
    assert match_mail_filter_rule(
        mail,
        [{"rule_type": "SUBJECT_KEYWORD", "pattern": "제품 뉴스"}],
    )
    assert (
        match_mail_filter_rule(
            mail,
            [{"rule_type": "SUBJECT_KEYWORD", "pattern": "비밀키워드"}],
        )
        is None
    )


def test_user_filter_rule_skips_llm_and_uses_existing_ignore_action(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    storage.initialize()
    rule = storage.add_mail_filter_rule(
        name="뉴스레터 제외",
        rule_type="SENDER_DOMAIN",
        pattern="example.test",
    )
    analyzer = RuleAwareMailAnalyzer(MockMailAnalyzer(), storage)
    workflow = MailTaskWorkflow(settings, storage, analyzer)

    result = workflow.process(_mail())

    assert result.proposal.action == AgentAction.IGNORE
    assert "뉴스레터 제외" in result.analysis.reason
    assert storage.list_tasks() == []
    assert storage.is_processed("FILTER-001")
    event = next(
        item
        for item in storage.list_events("FILTER-001")
        if item["step"] == "M-01 LLM_ANALYSIS" and item["status"] == "SUCCESS"
    )
    assert "LLM 호출 생략" in event["message"]

    storage.set_mail_filter_rule_enabled(rule["rule_id"], False)
    assert storage.list_mail_filter_rules()[0]["enabled"] is False
    storage.delete_mail_filter_rule(rule["rule_id"])
    assert storage.list_mail_filter_rules() == []


def test_disabled_filter_falls_through_to_existing_analyzer(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    storage.initialize()
    mail = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[0]
    rule = storage.add_mail_filter_rule(
        name="비활성 제외",
        rule_type="SENDER_EMAIL",
        pattern=mail.sender,
    )
    storage.set_mail_filter_rule_enabled(rule["rule_id"], False)
    workflow = MailTaskWorkflow(
        settings,
        storage,
        RuleAwareMailAnalyzer(MockMailAnalyzer(), storage),
    )

    result = workflow.process(mail)

    assert result.proposal.action == AgentAction.CREATE_TASK
    assert result.analysis.reason != "사용자 제외 Rule 적용"
