from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import uuid4

from mailtaskagent.config import Settings
from mailtaskagent.llm_client import MailAnalyzer
from mailtaskagent.models import MailInput
from mailtaskagent.priority import PriorityLevel, calculate_task_priority
from mailtaskagent.process_lock import interprocess_lock
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow


TRANSIENT_ERROR_TYPES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectionError",
    "RateLimitError",
    "TimeoutError",
}


class MailSource(Protocol):
    def load(self) -> list[MailInput]: ...


@dataclass(frozen=True)
class SyncRunReport:
    run_id: str
    source: str
    status: str
    fetched_count: int
    pending_count: int
    succeeded_count: int
    failed_count: int
    duplicate_count: int
    retry_count: int
    failed_mail_ids: tuple[str, ...] = ()
    error_type: str | None = None

    def model_dump(self) -> dict:
        result = asdict(self)
        result["failed_mail_ids"] = list(self.failed_mail_ids)
        return result


class MailSyncService:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: SQLiteStorage,
        analyzer: MailAnalyzer,
        source: MailSource,
        source_name: str,
        max_attempts: int = 2,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        self.settings = settings
        self.storage = storage
        self.analyzer = analyzer
        self.source = source
        self.source_name = source_name.strip().upper()
        self.max_attempts = max_attempts

    def run_once(self) -> SyncRunReport:
        lock_path = self.storage.path.with_name(f"{self.storage.path.name}.sync.lock")
        with interprocess_lock(lock_path) as acquired:
            if not acquired:
                return SyncRunReport(
                    run_id=f"SYNC-{uuid4().hex[:12].upper()}",
                    source=self.source_name,
                    status="SKIPPED",
                    fetched_count=0,
                    pending_count=0,
                    succeeded_count=0,
                    failed_count=0,
                    duplicate_count=0,
                    retry_count=0,
                    error_type="SyncAlreadyRunning",
                )
            return self._run_once_locked()

    def _run_once_locked(self) -> SyncRunReport:
        self.storage.initialize()
        run_id = f"SYNC-{uuid4().hex[:12].upper()}"
        self.storage.start_sync_run(run_id=run_id, source=self.source_name)
        try:
            mails = self.source.load()
        except Exception as exc:
            error_type = type(exc).__name__
            report = SyncRunReport(
                run_id=run_id,
                source=self.source_name,
                status="FAILED",
                fetched_count=0,
                pending_count=0,
                succeeded_count=0,
                failed_count=0,
                duplicate_count=0,
                retry_count=0,
                error_type=error_type,
            )
            self._finish(report)
            return report

        pending_mails = [
            mail for mail in mails if not self.storage.is_processed(mail.mail_id)
        ]
        workflow = MailTaskWorkflow(self.settings, self.storage, self.analyzer)
        succeeded_count = 0
        retry_count = 0
        failed_mail_ids: list[str] = []
        final_error_type: str | None = None

        for mail in pending_mails:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    workflow.process(mail)
                    succeeded_count += 1
                    break
                except Exception as exc:
                    error_type = type(exc).__name__
                    final_error_type = error_type
                    can_retry = (
                        attempt < self.max_attempts
                        and error_type in TRANSIENT_ERROR_TYPES
                    )
                    if can_retry:
                        retry_count += 1
                        continue
                    failed_mail_ids.append(mail.mail_id)
                    break

        failed_count = len(failed_mail_ids)
        if failed_count == 0:
            status = "SUCCESS"
            final_error_type = None
        elif succeeded_count:
            status = "PARTIAL"
        else:
            status = "FAILED"
        report = SyncRunReport(
            run_id=run_id,
            source=self.source_name,
            status=status,
            fetched_count=len(mails),
            pending_count=len(pending_mails),
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            duplicate_count=len(mails) - len(pending_mails),
            retry_count=retry_count,
            failed_mail_ids=tuple(failed_mail_ids),
            error_type=final_error_type,
        )
        self._finish(report)
        return report

    def _finish(self, report: SyncRunReport) -> None:
        self.storage.finish_sync_run(
            run_id=report.run_id,
            status=report.status,
            fetched_count=report.fetched_count,
            pending_count=report.pending_count,
            succeeded_count=report.succeeded_count,
            failed_count=report.failed_count,
            duplicate_count=report.duplicate_count,
            retry_count=report.retry_count,
            error_type=report.error_type,
        )


def build_attention_snapshot(
    storage: SQLiteStorage,
    *,
    today: date | None = None,
    limit: int = 25,
) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError("Attention limit must be between 1 and 100")
    storage.initialize()
    rules = storage.list_priority_rules()
    settings = storage.get_priority_settings()
    active_tasks = [
        task
        for task in storage.list_tasks()
        if task["status"] not in {"COMPLETED", "CANCELLED"}
    ]
    decisions = {
        task["task_id"]: calculate_task_priority(
            task,
            rules,
            settings,
            today=today,
        )
        for task in active_tasks
    }
    ordered = sorted(
        active_tasks,
        key=lambda task: (
            int(decisions[task["task_id"]].level.value[-1]),
            task.get("due_date") or "9999-12-31",
            task["task_id"],
        ),
    )
    counts = {
        level.value: sum(
            decision.level == level for decision in decisions.values()
        )
        for level in PriorityLevel
    }
    sync_runs = storage.list_sync_runs(limit=1)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "active_task_count": len(active_tasks),
        "pending_review_count": len(storage.list_pending_reviews()),
        "priority_counts": counts,
        "tasks": [
            {
                "task_id": task["task_id"],
                "title": task["title"],
                "status": task["status"],
                "due_date": task.get("due_date"),
                "priority": decisions[task["task_id"]].level.value,
                "priority_reason": decisions[task["task_id"]].reason,
            }
            for task in ordered[:limit]
        ],
        "last_sync": sync_runs[0] if sync_runs else None,
    }
