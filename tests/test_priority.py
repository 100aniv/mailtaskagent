from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from mailtaskagent.config import PROJECT_ROOT, Settings
from mailtaskagent.llm_client import MockMailAnalyzer
from mailtaskagent.priority import PriorityLevel, calculate_task_priority
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow, load_mails


def test_priority_combines_due_date_and_user_rules() -> None:
    rules = [
        {
            "name": "ABC 고객사",
            "rule_type": "SENDER_DOMAIN",
            "pattern": "abc.co.kr",
            "importance": 1,
            "enabled": True,
        }
    ]
    task = {
        "title": "장애 원인 확인",
        "description": "서비스 상태를 확인합니다.",
        "requester": "owner@abc.co.kr",
        "due_date": "2026-08-30",
        "waiting_since": None,
        "importance_override": None,
    }

    decision = calculate_task_priority(task, rules, today=date(2026, 8, 28))

    assert decision.level == PriorityLevel.P1
    assert decision.display == "🔴 즉시 처리"
    assert "ABC 고객사 Rule P1" in decision.reasons
    assert "기한 2일 남음" in decision.reasons


def test_manual_importance_overrides_matching_rule() -> None:
    task = {
        "title": "일반 확인",
        "description": None,
        "requester": "owner@abc.co.kr",
        "due_date": None,
        "waiting_since": None,
        "importance_override": 4,
    }
    rules = [
        {
            "name": "ABC 고객사",
            "rule_type": "SENDER_DOMAIN",
            "pattern": "abc.co.kr",
            "importance": 1,
            "enabled": True,
        }
    ]

    decision = calculate_task_priority(task, rules, today=date(2026, 8, 28))

    assert decision.level == PriorityLevel.P4
    assert decision.reasons == ("사용자 중요도 P4",)


def test_waiting_threshold_raises_priority() -> None:
    task = {
        "title": "고객 회신 확인",
        "description": None,
        "requester": None,
        "due_date": None,
        "waiting_since": "2026-08-24T09:00:00+00:00",
        "importance_override": None,
    }

    decision = calculate_task_priority(
        task,
        settings={"waiting_attention_days": 3},
        today=date(2026, 8, 28),
        now=datetime(2026, 8, 28, 9, 0, tzinfo=UTC),
    )

    assert decision.level == PriorityLevel.P2
    assert "회신 4일 대기" in decision.reasons


def test_priority_rule_settings_and_task_override_are_persisted(tmp_path: Path) -> None:
    settings = Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=tmp_path / "priority.db",
        confidence_threshold=0.75,
    )
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())
    created = workflow.process(load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[0])

    rule = storage.add_priority_rule(
        name="요청자 우선",
        rule_type="SENDER_EMAIL",
        pattern=created.task["requester"],
        importance=1,
    )
    assert storage.list_priority_rules()[0]["rule_id"] == rule["rule_id"]

    storage.set_priority_rule_enabled(rule["rule_id"], False)
    assert storage.list_priority_rules()[0]["enabled"] is False
    storage.set_priority_rule_enabled(rule["rule_id"], True)

    updated_settings = storage.update_priority_settings(
        {"due_soon_days": 2, "due_later_days": 6, "waiting_attention_days": 4}
    )
    assert updated_settings == {
        "due_soon_days": 2,
        "due_later_days": 6,
        "waiting_attention_days": 4,
    }

    result = storage.set_task_importance(created.task["task_id"], 2)
    assert result["after"]["importance_override"] == 2
    history = storage.list_histories()[0]
    assert json.loads(history["user_decision"])["decision"] == "PRIORITY_OVERRIDE"

    storage.set_task_importance(created.task["task_id"], None)
    assert storage.get_task(created.task["task_id"])["importance_override"] is None

    storage.delete_priority_rule(rule["rule_id"])
    assert storage.list_priority_rules() == []


def test_operation_auto_sync_settings_are_persisted_and_validated(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "operation-settings.db")
    storage.initialize()

    assert storage.get_operation_settings() == {
        "gmail_auto_sync_enabled": False,
        "gmail_sync_interval_minutes": 5,
    }

    updated = storage.update_operation_settings(
        gmail_auto_sync_enabled=True,
        gmail_sync_interval_minutes=10,
    )

    assert updated == {
        "gmail_auto_sync_enabled": True,
        "gmail_sync_interval_minutes": 10,
    }
    assert storage.get_operation_settings() == updated

    with pytest.raises(ValueError, match="between 1 and 60"):
        storage.update_operation_settings(
            gmail_auto_sync_enabled=True,
            gmail_sync_interval_minutes=0,
        )
