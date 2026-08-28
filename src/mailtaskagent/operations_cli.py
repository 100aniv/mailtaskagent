from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from mailtaskagent.config import PROJECT_ROOT, load_settings
from mailtaskagent.gmail_source import (
    GmailReadOnlySource,
    build_gmail_service,
    load_gmail_source_settings,
)
from mailtaskagent.mail_filters import build_operational_analyzer
from mailtaskagent.operations import MailSyncService, build_attention_snapshot
from mailtaskagent.storage import SQLiteStorage


class _ConfiguredGmailSource:
    def load(self):
        gmail_settings = load_gmail_source_settings()
        service = build_gmail_service(gmail_settings)
        return GmailReadOnlySource(service, gmail_settings).load()


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str))


def _default_backup_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_ROOT / "data" / "backups" / f"mailtaskagent-{stamp}.db"


def _run_sync_gmail() -> int:
    settings = load_settings()
    storage = SQLiteStorage(settings.database_path)
    service = MailSyncService(
        settings=settings,
        storage=storage,
        analyzer=build_operational_analyzer(settings, storage),
        source=_ConfiguredGmailSource(),
        source_name="GMAIL",
    )
    report = service.run_once()
    _print_json(report.model_dump())
    if report.status == "FAILED":
        return 2
    if report.status == "PARTIAL":
        return 1
    return 0


def _run_status(limit: int) -> int:
    settings = load_settings()
    storage = SQLiteStorage(settings.database_path)
    snapshot = build_attention_snapshot(storage, limit=limit)
    snapshot["llm_mode"] = settings.llm_mode
    _print_json(snapshot)
    return 0


def _run_backup(output: Path | None) -> int:
    settings = load_settings()
    storage = SQLiteStorage(settings.database_path)
    destination = storage.backup_to(output or _default_backup_path())
    _print_json(
        {
            "status": "SUCCESS",
            "backup_path": str(destination),
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    return 0


def _run_health() -> int:
    settings = load_settings()
    storage = SQLiteStorage(settings.database_path)
    storage.initialize()
    gmail_settings = load_gmail_source_settings()
    latest_runs = storage.list_sync_runs(source="GMAIL", limit=1)
    checks = {
        "database_ready": settings.database_path.exists(),
        "llm_ready": settings.use_mock or bool(settings.api_key),
        "gmail_credentials_ready": gmail_settings.credentials_path.exists(),
        "gmail_token_ready": gmail_settings.token_path.exists(),
    }
    status = "READY" if all(checks.values()) else "DEGRADED"
    _print_json(
        {
            "status": status,
            "checks": checks,
            "last_sync_status": latest_runs[0]["status"] if latest_runs else None,
            "checked_at": datetime.now(UTC).isoformat(),
        }
    )
    return 0 if status == "READY" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MailTaskAgent scheduler-safe operations commands."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "sync-gmail",
        help="Fetch the restricted Gmail label once and process only new mail IDs.",
    )
    subparsers.add_parser(
        "health",
        help="Check local DB, LLM configuration and Gmail OAuth readiness.",
    )
    status_parser = subparsers.add_parser(
        "status",
        help="Print task attention and last sync status as one JSON object.",
    )
    status_parser.add_argument("--limit", type=int, default=25)
    backup_parser = subparsers.add_parser(
        "backup",
        help="Create a recoverable SQLite backup and print its local path.",
    )
    backup_parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "sync-gmail":
            return _run_sync_gmail()
        if args.command == "status":
            return _run_status(args.limit)
        if args.command == "health":
            return _run_health()
        return _run_backup(args.output)
    except Exception as exc:
        _print_json({"status": "FAILED", "error_type": type(exc).__name__})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
