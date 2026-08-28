from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from mailtaskagent.config import PROJECT_ROOT, Settings
from mailtaskagent.llm_client import MockMailAnalyzer
from mailtaskagent.operations import MailSyncService
from mailtaskagent.operations import build_attention_snapshot
from mailtaskagent.operations_cli import main as operations_main
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import load_mails


class _StaticSource:
    def __init__(self, mails) -> None:
        self.mails = mails

    def load(self):
        return self.mails


class _FailingSource:
    def load(self):
        raise ConnectionError("synthetic source failure")


class _RetryOnceAnalyzer:
    def __init__(self) -> None:
        self.calls = 0
        self.delegate = MockMailAnalyzer()

    def analyze(self, mail):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("synthetic timeout")
        return self.delegate.analyze(mail)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=tmp_path / "operations.db",
        confidence_threshold=0.75,
    )


def test_sync_service_records_success_and_duplicate_counts(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    mails = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[:2]
    service = MailSyncService(
        settings=settings,
        storage=storage,
        analyzer=MockMailAnalyzer(),
        source=_StaticSource(mails),
        source_name="GMAIL",
    )

    first = service.run_once()
    second = service.run_once()

    assert first.status == "SUCCESS"
    assert first.fetched_count == 2
    assert first.pending_count == 2
    assert first.succeeded_count == 2
    assert second.status == "SUCCESS"
    assert second.pending_count == 0
    assert second.duplicate_count == 2
    runs = storage.list_sync_runs(source="GMAIL")
    assert [run["status"] for run in runs] == ["SUCCESS", "SUCCESS"]
    assert runs[0]["duplicate_count"] == 2


def test_sync_service_retries_only_transient_failure(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    analyzer = _RetryOnceAnalyzer()
    service = MailSyncService(
        settings=settings,
        storage=storage,
        analyzer=analyzer,
        source=_StaticSource(
            load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[:1]
        ),
        source_name="GMAIL",
    )

    report = service.run_once()

    assert report.status == "SUCCESS"
    assert report.succeeded_count == 1
    assert report.retry_count == 1
    assert report.error_type is None
    assert analyzer.calls == 2


def test_sync_service_records_source_failure_without_error_message(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    service = MailSyncService(
        settings=settings,
        storage=storage,
        analyzer=MockMailAnalyzer(),
        source=_FailingSource(),
        source_name="GMAIL",
    )

    report = service.run_once()

    assert report.status == "FAILED"
    assert report.error_type == "ConnectionError"
    assert "synthetic source failure" not in str(report.model_dump())
    run = storage.list_sync_runs(limit=1)[0]
    assert run["error_type"] == "ConnectionError"


def test_attention_snapshot_contains_only_operational_task_fields(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    service = MailSyncService(
        settings=settings,
        storage=storage,
        analyzer=MockMailAnalyzer(),
        source=_StaticSource(
            load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[:1]
        ),
        source_name="GMAIL",
    )
    service.run_once()

    snapshot = build_attention_snapshot(storage)

    assert snapshot["active_task_count"] == 1
    assert snapshot["last_sync"]["status"] == "SUCCESS"
    assert set(snapshot["tasks"][0]) == {
        "task_id",
        "title",
        "status",
        "due_date",
        "priority",
        "priority_reason",
    }


def test_operations_cli_status_and_backup_are_machine_readable(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    database_path = tmp_path / "ops-cli.db"
    backup_path = tmp_path / "backups" / "ops-cli-backup.db"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")

    assert operations_main(["status", "--limit", "10"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["llm_mode"] == "MOCK"
    assert status_payload["active_task_count"] == 0

    assert operations_main(["backup", "--output", str(backup_path)]) == 0
    backup_payload = json.loads(capsys.readouterr().out)
    assert backup_payload["status"] == "SUCCESS"
    assert Path(backup_payload["backup_path"]) == backup_path.resolve()
    assert backup_path.exists()


def test_operations_cli_health_reports_readiness_without_secrets(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "health.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv(
        "GMAIL_CREDENTIALS_PATH", str(tmp_path / "missing-credentials.json")
    )
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "missing-token.json"))

    assert operations_main(["health"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "DEGRADED"
    assert payload["checks"]["database_ready"] is True
    assert payload["checks"]["llm_ready"] is True
    assert payload["checks"]["gmail_token_ready"] is False
    assert "api_key" not in str(payload).casefold()


def test_sqlite_backup_can_be_opened_with_task_and_history(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "source.db")
    storage.initialize()
    task = storage.create_task_by_user(title="백업 검증 업무", importance=1)
    backup_path = storage.backup_to(tmp_path / "backups" / "restorable.db")

    restored = SQLiteStorage(backup_path)
    restored.initialize()

    assert restored.get_task(task["task_id"])["title"] == "백업 검증 업무"
    assert restored.list_histories()[0]["task_id"] == task["task_id"]


def test_initialize_migrates_mvp_database_to_post_mvp_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-mvp.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                title TEXT NOT NULL,
                requester TEXT,
                description TEXT,
                due_date TEXT,
                reply_required INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                source_mail_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()

    storage = SQLiteStorage(database_path)
    storage.initialize()

    with storage.connect() as connection:
        task_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(tasks)")
        }
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"waiting_since", "importance_override"} <= task_columns
    assert {"sync_runs", "operation_settings", "mail_filter_rules"} <= tables
