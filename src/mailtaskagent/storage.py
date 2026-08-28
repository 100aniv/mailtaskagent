from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from mailtaskagent.models import (
    ActionProposal,
    AgentAction,
    MailAnalysis,
    MailInput,
    ReviewDecision,
    TaskCandidate,
    TaskStatus,
)
from mailtaskagent.policy import validate_status_transition
from mailtaskagent.mail_filters import MailFilterRuleType
from mailtaskagent.priority import PriorityRuleType


SCHEMA = """
CREATE TABLE IF NOT EXISTS mails (
    mail_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    sender TEXT NOT NULL,
    recipients_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    title TEXT NOT NULL,
    requester TEXT,
    description TEXT,
    due_date TEXT,
    reply_required INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    waiting_since TEXT,
    importance_override INTEGER,
    source_mail_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_conversation ON tasks(conversation_id);
CREATE TABLE IF NOT EXISTS mail_task_links (
    link_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mail_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(mail_id, task_id)
);
CREATE TABLE IF NOT EXISTS histories (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    mail_id TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    user_decision TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processing_results (
    mail_id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    task_id TEXT,
    result_json TEXT NOT NULL,
    processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processing_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    mail_id TEXT NOT NULL,
    step TEXT NOT NULL,
    level TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_processing_events_mail ON processing_events(mail_id, event_id);
CREATE TABLE IF NOT EXISTS priority_rules (
    rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    importance INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(rule_type, pattern)
);
CREATE TABLE IF NOT EXISTS mail_filter_rules (
    rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(rule_type, pattern)
);
CREATE TABLE IF NOT EXISTS priority_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operation_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    pending_count INTEGER NOT NULL DEFAULT 0,
    succeeded_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_type TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_runs_source_started
ON sync_runs(source, started_at DESC);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object | None) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def _sanitize(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(
                secret in normalized
                for secret in (
                    "api_key",
                    "authorization",
                    "credential",
                    "password",
                    "token",
                    "secret",
                )
            ):
                result[key] = "[REDACTED]"
            else:
                result[key] = _sanitize(item)
        return result
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        redacted = re.sub(r"atl-[A-Za-z0-9._-]+", "[REDACTED]", value, flags=re.IGNORECASE)
        redacted = re.sub(
            r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
            "Bearer [REDACTED]",
            redacted,
        )
        redacted = re.sub(
            r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
            "[REDACTED]",
            redacted,
        )
        redacted = re.sub(
            r"(?i)(api[-_ ]?key|authorization|client[-_ ]?secret|access[-_ ]?token|refresh[-_ ]?token)(\s*[:=]\s*)([^\s,;]+)",
            r"\1\2[REDACTED]",
            redacted,
        )
        return redacted
    return value


def _match_tokens(text: str) -> set[str]:
    stop_words = {"관련", "요청", "확인", "추가", "업무", "주세요", "드립니다", "결과"}
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9가-힣]+", text)
        if len(token) >= 2 and token not in stop_words
    }


class SQLiteStorage:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "waiting_since" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN waiting_since TEXT")
            if "importance_override" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN importance_override INTEGER")
            connection.commit()

    def reset(self) -> None:
        self.initialize()
        with self.connect() as connection:
            connection.execute("DELETE FROM sync_runs")
            connection.execute("DELETE FROM processing_events")
            connection.execute("DELETE FROM processing_results")
            connection.execute("DELETE FROM histories")
            connection.execute("DELETE FROM mail_task_links")
            connection.execute("DELETE FROM tasks")
            connection.execute("DELETE FROM mails")
            connection.commit()

    def append_event(
        self,
        *,
        case_id: str,
        mail_id: str,
        step: str,
        status: str,
        message: str,
        level: str = "INFO",
        details: dict | list | None = None,
        duration_ms: int | None = None,
    ) -> None:
        safe_details = _sanitize(details)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO processing_events(case_id, mail_id, step, level, status,
                                              message, details_json, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    mail_id,
                    step,
                    level,
                    status,
                    _sanitize(message),
                    _json(safe_details),
                    duration_ms,
                    _now(),
                ),
            )
            connection.commit()

    def list_events(self, mail_id: str | None = None) -> list[dict]:
        query = "SELECT * FROM processing_events"
        params: tuple[str, ...] = ()
        if mail_id:
            query += " WHERE mail_id = ?"
            params = (mail_id,)
        query += " ORDER BY event_id DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def is_processed(self, mail_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM processing_results WHERE mail_id = ?", (mail_id,)
            ).fetchone()
            return row is not None

    def get_processing_result(self, mail_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM processing_results WHERE mail_id = ?", (mail_id,)
            ).fetchone()
            return json.loads(row["result_json"]) if row else None

    def list_processing_results(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT mail_id, action, task_id, result_json, processed_at
                FROM processing_results
                ORDER BY processed_at DESC
                """
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json"))
            results.append(item)
        return results

    def list_thread_mails(self, conversation_id: str, *, limit: int = 10) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT mail_id, conversation_id, direction, sender, recipients_json,
                       occurred_at, subject, body, processed_at
                FROM mails
                WHERE conversation_id = ?
                ORDER BY occurred_at DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["recipients"] = json.loads(item.pop("recipients_json"))
            result.append(item)
        return result

    def get_task_context(self, task_id: str, *, history_limit: int = 10) -> dict | None:
        with self.connect() as connection:
            task = self._fetch_task(connection, task_id)
            if task is None:
                return None
            linked_mails = connection.execute(
                """
                SELECT l.mail_id, l.link_type, l.reason, l.confidence, l.created_at,
                       m.direction, m.sender, m.occurred_at, m.subject
                FROM mail_task_links AS l
                LEFT JOIN mails AS m ON m.mail_id = l.mail_id
                WHERE l.task_id = ?
                ORDER BY l.link_id DESC
                """,
                (task_id,),
            ).fetchall()
            histories = connection.execute(
                """
                SELECT history_id, task_id, mail_id, action, before_json, after_json,
                       reason, confidence, user_decision, created_at
                FROM histories
                WHERE task_id = ?
                ORDER BY history_id DESC
                LIMIT ?
                """,
                (task_id, history_limit),
            ).fetchall()
        return {
            "task": task,
            "linked_mails": [dict(row) for row in linked_mails],
            "recent_histories": [dict(row) for row in histories],
        }

    def find_active_task_by_conversation(self, conversation_id: str) -> TaskCandidate | None:
        candidates = self.search_candidate_tasks(conversation_id, "", include_related=False)
        return candidates[0] if candidates else None

    def search_candidate_tasks(
        self,
        conversation_id: str,
        query_text: str,
        *,
        include_related: bool,
        limit: int = 5,
    ) -> list[TaskCandidate]:
        with self.connect() as connection:
            exact_rows = connection.execute(
                """
                SELECT task_id, conversation_id, title, requester, description, due_date,
                       reply_required, status, waiting_since
                FROM tasks
                WHERE conversation_id = ? AND status NOT IN ('COMPLETED', 'CANCELLED')
                ORDER BY updated_at DESC
                """,
                (conversation_id,),
            ).fetchall()
            if exact_rows:
                return [
                    self._candidate_from_row(row).model_copy(
                        update={
                            "match_score": 1.0,
                            "match_reason": "동일 conversation_id",
                        }
                    )
                    for row in exact_rows[:limit]
                ]
            if not include_related:
                return []
            rows = connection.execute(
                """
                SELECT task_id, conversation_id, title, requester, description, due_date,
                       reply_required, status, waiting_since
                FROM tasks
                WHERE status NOT IN ('COMPLETED', 'CANCELLED')
                ORDER BY updated_at DESC
                """
            ).fetchall()

        query_tokens = _match_tokens(query_text)
        ranked: list[tuple[int, TaskCandidate]] = []
        for row in rows:
            candidate = self._candidate_from_row(row)
            candidate_tokens = _match_tokens(
                " ".join(filter(None, [candidate.title, candidate.description, candidate.requester]))
            )
            matched_tokens = sorted(query_tokens & candidate_tokens)
            score = len(matched_tokens)
            if score:
                normalized_score = min(1.0, score / max(1, len(query_tokens)))
                candidate = candidate.model_copy(
                    update={
                        "match_score": normalized_score,
                        "match_reason": f"제목·요청자·내용 일치: {', '.join(matched_tokens)}",
                    }
                )
                ranked.append((score, candidate))
        ranked.sort(key=lambda item: (-item[0], -item[1].match_score, item[1].task_id))
        return [candidate for _, candidate in ranked[:limit]]

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> TaskCandidate:
        data = dict(row)
        data["reply_required"] = bool(data["reply_required"])
        return TaskCandidate.model_validate(data)

    def get_task(self, task_id: str) -> dict | None:
        with self.connect() as connection:
            return self._fetch_task(connection, task_id)

    def _next_task_id(self, connection: sqlite3.Connection) -> str:
        rows = connection.execute("SELECT task_id FROM tasks").fetchall()
        numbers = [int(row["task_id"].split("-")[-1]) for row in rows if row["task_id"].startswith("TASK-")]
        return f"TASK-{max(numbers, default=0) + 1:03d}"

    def _insert_mail(self, connection: sqlite3.Connection, mail: MailInput, now: str) -> None:
        connection.execute(
            """
            INSERT INTO mails(mail_id, conversation_id, direction, sender, recipients_json,
                              occurred_at, subject, body, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mail.mail_id,
                mail.conversation_id,
                mail.direction.value,
                mail.sender,
                _json(mail.recipients),
                mail.occurred_at.isoformat(),
                mail.subject,
                mail.body,
                now,
            ),
        )

    def apply(
        self,
        case_id: str,
        mail: MailInput,
        analysis: MailAnalysis,
        proposal: ActionProposal,
        candidate_tasks: list[TaskCandidate],
        *,
        thread_history: list[dict] | None = None,
        current_task_context: dict | None = None,
        validation_result: dict | None = None,
    ) -> tuple[dict | None, dict | None, dict | None]:
        now = _now()
        with self.connect() as connection:
            try:
                connection.execute("BEGIN")
                if connection.execute(
                    "SELECT 1 FROM processing_results WHERE mail_id = ?", (mail.mail_id,)
                ).fetchone():
                    raise ValueError(f"Mail already processed: {mail.mail_id}")
                self._insert_mail(connection, mail, now)

                task: dict | None = None
                before: dict | None = None
                after: dict | None = None
                task_id = proposal.target_task_id

                if proposal.action == AgentAction.CREATE_TASK:
                    task_id = self._next_task_id(connection)
                    payload = proposal.task_payload
                    connection.execute(
                        """
                        INSERT INTO tasks(task_id, conversation_id, title, requester, description,
                                          due_date, reply_required, status, source_mail_id,
                                          created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task_id,
                            payload["conversation_id"],
                            payload["title"],
                            payload.get("requester"),
                            payload.get("description"),
                            payload.get("due_date"),
                            int(payload.get("reply_required", False)),
                            payload["status"],
                            mail.mail_id,
                            now,
                            now,
                        ),
                    )
                    after = self._fetch_task(connection, task_id)
                    task = after
                    self._insert_link(
                        connection,
                        mail.mail_id,
                        task_id,
                        AgentAction.CREATE_TASK.value,
                        proposal.reason,
                        proposal.confidence,
                        now,
                    )

                elif proposal.action in {AgentAction.UPDATE_TASK, AgentAction.SET_WAITING}:
                    if not task_id:
                        raise ValueError(f"{proposal.action.value} requires target_task_id")
                    before = self._fetch_task(connection, task_id)
                    if before is None:
                        raise ValueError(f"Task not found: {task_id}")
                    allowed = {
                        "title",
                        "description",
                        "due_date",
                        "reply_required",
                        "status",
                        "waiting_since",
                    }
                    invalid = set(proposal.changes) - allowed
                    if invalid:
                        raise ValueError(f"Unsupported task changes: {sorted(invalid)}")
                    if not proposal.changes:
                        raise ValueError(f"{proposal.action.value} requires at least one change")
                    if "status" in proposal.changes:
                        validate_status_transition(before["status"], proposal.changes["status"])
                    assignments = ", ".join(f"{key} = ?" for key in proposal.changes)
                    values = [int(v) if isinstance(v, bool) else v for v in proposal.changes.values()]
                    connection.execute(
                        f"UPDATE tasks SET {assignments}, updated_at = ? WHERE task_id = ?",
                        (*values, now, task_id),
                    )
                    after = self._fetch_task(connection, task_id)
                    task = after
                    self._insert_link(
                        connection,
                        mail.mail_id,
                        task_id,
                        proposal.action.value,
                        proposal.reason,
                        proposal.confidence,
                        now,
                    )

                elif proposal.action == AgentAction.LINK_TO_TASK:
                    if not task_id:
                        raise ValueError("LINK_TO_TASK requires target_task_id")
                    task = self._fetch_task(connection, task_id)
                    if task is None:
                        raise ValueError(f"Task not found: {task_id}")
                    before = task
                    after = task
                    self._insert_link(
                        connection,
                        mail.mail_id,
                        task_id,
                        proposal.action.value,
                        proposal.reason,
                        proposal.confidence,
                        now,
                    )

                elif proposal.action == AgentAction.MARK_COMPLETED:
                    if not task_id:
                        raise ValueError("MARK_COMPLETED requires target_task_id")
                    task = self._fetch_task(connection, task_id)
                    if task is None:
                        raise ValueError(f"Task not found: {task_id}")
                    before = task

                history_after = after or {"processing": proposal.action.value}
                connection.execute(
                    """
                    INSERT INTO histories(task_id, mail_id, action, before_json, after_json,
                                          reason, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        mail.mail_id,
                        proposal.action.value,
                        _json(before),
                        _json(history_after),
                        proposal.reason,
                        proposal.confidence,
                        now,
                    ),
                )
                result = {
                    "case_id": case_id,
                    "mail_id": mail.mail_id,
                    "analysis": analysis.model_dump(mode="json"),
                    "proposal": proposal.model_dump(mode="json"),
                    "thread_history": thread_history or [],
                    "candidate_tasks": [item.model_dump(mode="json") for item in candidate_tasks],
                    "current_task_context": current_task_context,
                    "validation_result": validation_result or {},
                    "action": proposal.action.value,
                    "task_id": task_id,
                    "task": task,
                    "before": before,
                    "after": after,
                }
                connection.execute(
                    """
                    INSERT INTO processing_results(mail_id, action, task_id, result_json, processed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (mail.mail_id, proposal.action.value, task_id, _json(result), now),
                )
                connection.commit()
                return task, before, after
            except Exception:
                connection.rollback()
                raise

    def _insert_link(
        self,
        connection: sqlite3.Connection,
        mail_id: str,
        task_id: str,
        link_type: str,
        reason: str,
        confidence: float,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO mail_task_links(
                mail_id, task_id, link_type, reason, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (mail_id, task_id, link_type, reason, confidence, now),
        )

    def resolve_review(
        self,
        *,
        mail: MailInput,
        decision: ReviewDecision,
        target_task_id: str | None = None,
        new_task_title: str | None = None,
        approved_changes: dict | None = None,
    ) -> dict:
        now = _now()
        with self.connect() as connection:
            try:
                connection.execute("BEGIN")
                row = connection.execute(
                    "SELECT result_json FROM processing_results WHERE mail_id = ?",
                    (mail.mail_id,),
                ).fetchone()
                if not row:
                    raise ValueError(f"Pending review not found: {mail.mail_id}")
                stored = json.loads(row["result_json"])
                stored_proposal = ActionProposal.model_validate(stored.get("proposal", {}))
                if not stored_proposal.needs_user_confirmation:
                    raise ValueError("This result does not require user review")
                if stored.get("review_result"):
                    raise ValueError("Review already resolved")

                analysis = MailAnalysis.model_validate(stored["analysis"])
                candidate_ids = {
                    candidate["task_id"] for candidate in stored.get("candidate_tasks", [])
                }
                final_action: AgentAction
                task_id: str | None = None
                task: dict | None = None
                before: dict | None = None
                after: dict | None = None

                if stored_proposal.action == AgentAction.MARK_COMPLETED:
                    task_id = stored_proposal.target_task_id
                    if not task_id or task_id not in candidate_ids:
                        raise ValueError("Completion target must be a listed candidate Task")
                    before = self._fetch_task(connection, task_id)
                    if not before:
                        raise ValueError(f"Task not found: {task_id}")
                    if decision == ReviewDecision.APPROVE_PROPOSAL:
                        validate_status_transition(before["status"], TaskStatus.COMPLETED)
                        connection.execute(
                            """
                            UPDATE tasks
                            SET status = ?, waiting_since = NULL, updated_at = ?
                            WHERE task_id = ?
                            """,
                            (TaskStatus.COMPLETED.value, now, task_id),
                        )
                        after = self._fetch_task(connection, task_id)
                        task = after
                        final_action = AgentAction.MARK_COMPLETED
                        self._insert_link(
                            connection,
                            mail.mail_id,
                            task_id,
                            final_action.value,
                            "사용자가 Agent 완료 제안을 승인",
                            1.0,
                            now,
                        )
                    elif decision == ReviewDecision.IGNORE:
                        task = before
                        after = before
                        final_action = AgentAction.IGNORE
                    else:
                        raise ValueError("Completion review supports approve or ignore only")

                elif stored_proposal.changes.get("status") == TaskStatus.CANCELLED.value:
                    task_id = stored_proposal.target_task_id
                    if not task_id or task_id not in candidate_ids:
                        raise ValueError("Cancellation target must be a listed candidate Task")
                    before = self._fetch_task(connection, task_id)
                    if not before:
                        raise ValueError(f"Task not found: {task_id}")
                    if decision == ReviewDecision.APPROVE_PROPOSAL:
                        validate_status_transition(before["status"], TaskStatus.CANCELLED)
                        connection.execute(
                            """
                            UPDATE tasks
                            SET status = ?, waiting_since = NULL, updated_at = ?
                            WHERE task_id = ?
                            """,
                            (TaskStatus.CANCELLED.value, now, task_id),
                        )
                        after = self._fetch_task(connection, task_id)
                        task = after
                        final_action = AgentAction.UPDATE_TASK
                        self._insert_link(
                            connection,
                            mail.mail_id,
                            task_id,
                            final_action.value,
                            "사용자가 Agent 취소 제안을 승인",
                            1.0,
                            now,
                        )
                    elif decision == ReviewDecision.IGNORE:
                        task = before
                        after = before
                        final_action = AgentAction.IGNORE
                    else:
                        raise ValueError("Cancellation review supports approve or ignore only")

                elif stored_proposal.action == AgentAction.ASK_USER and stored_proposal.changes:
                    task_id = stored_proposal.target_task_id
                    if not task_id or task_id not in candidate_ids:
                        raise ValueError("Change target must be a listed candidate Task")
                    before = self._fetch_task(connection, task_id)
                    if not before:
                        raise ValueError(f"Task not found: {task_id}")
                    if decision == ReviewDecision.APPROVE_PROPOSAL:
                        changes = approved_changes or stored_proposal.changes
                        allowed = {"due_date"}
                        invalid = set(changes) - allowed
                        if invalid or not changes:
                            raise ValueError("Review change supports due_date only")
                        connection.execute(
                            "UPDATE tasks SET due_date = ?, updated_at = ? WHERE task_id = ?",
                            (changes.get("due_date"), now, task_id),
                        )
                        after = self._fetch_task(connection, task_id)
                        task = after
                        final_action = AgentAction.UPDATE_TASK
                        self._insert_link(
                            connection,
                            mail.mail_id,
                            task_id,
                            final_action.value,
                            "사용자가 중요 변경 값을 확인하고 승인",
                            1.0,
                            now,
                        )
                    elif decision == ReviewDecision.IGNORE:
                        task = before
                        after = before
                        final_action = AgentAction.IGNORE
                    else:
                        raise ValueError("Change review supports approve or ignore only")

                elif decision == ReviewDecision.LINK_EXISTING:
                    if not target_task_id or target_task_id not in candidate_ids:
                        raise ValueError("A listed candidate Task must be selected")
                    task_id = target_task_id
                    task = self._fetch_task(connection, task_id)
                    if not task:
                        raise ValueError(f"Task not found: {task_id}")
                    before = task
                    after = task
                    final_action = AgentAction.LINK_TO_TASK
                    self._insert_link(
                        connection,
                        mail.mail_id,
                        task_id,
                        final_action.value,
                        "사용자가 ASK_USER 후보 중 기존 Task 연결을 확정",
                        1.0,
                        now,
                    )

                elif decision == ReviewDecision.CREATE_NEW:
                    title = (new_task_title or "").strip()
                    if not title:
                        raise ValueError("New Task title is required")
                    task_id = self._next_task_id(connection)
                    connection.execute(
                        """
                        INSERT INTO tasks(task_id, conversation_id, title, requester, description,
                                          due_date, reply_required, status, source_mail_id,
                                          created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task_id,
                            mail.conversation_id,
                            title,
                            analysis.requester,
                            analysis.request_summary,
                            analysis.due_date.isoformat() if analysis.due_date else None,
                            int(analysis.reply_required),
                            TaskStatus.TODO.value,
                            mail.mail_id,
                            now,
                            now,
                        ),
                    )
                    after = self._fetch_task(connection, task_id)
                    task = after
                    final_action = AgentAction.CREATE_TASK
                    self._insert_link(
                        connection,
                        mail.mail_id,
                        task_id,
                        final_action.value,
                        "사용자가 ASK_USER 검토에서 신규 Task 생성을 확정",
                        1.0,
                        now,
                    )

                elif decision == ReviewDecision.IGNORE:
                    final_action = AgentAction.IGNORE
                else:
                    raise ValueError("Unsupported ASK_USER review decision")

                decision_payload = {
                    "decision": decision.value,
                    "target_task_id": task_id,
                    "new_task_title": new_task_title if decision == ReviewDecision.CREATE_NEW else None,
                    "approved_changes": approved_changes,
                }
                reason = (
                    f"사용자가 {stored_proposal.action.value} 검토 결과를 "
                    f"{final_action.value}로 확정"
                )
                connection.execute(
                    """
                    INSERT INTO histories(task_id, mail_id, action, before_json, after_json,
                                          reason, confidence, user_decision, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        mail.mail_id,
                        final_action.value,
                        _json(before),
                        _json(after or {"processing": final_action.value}),
                        reason,
                        1.0,
                        _json(decision_payload),
                        now,
                    ),
                )
                review_result = {
                    "decision": decision.value,
                    "final_action": final_action.value,
                    "task_id": task_id,
                    "task": task,
                    "before": before,
                    "after": after,
                    "resolved_at": now,
                }
                stored["review_result"] = review_result
                stored["task"] = task
                stored["before"] = before
                stored["after"] = after
                connection.execute(
                    "UPDATE processing_results SET result_json = ? WHERE mail_id = ?",
                    (_json(stored), mail.mail_id),
                )
                connection.commit()
                return review_result
            except Exception:
                connection.rollback()
                raise

    def list_pending_reviews(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT result_json FROM processing_results ORDER BY processed_at",
            ).fetchall()
        pending = []
        for row in rows:
            result = json.loads(row["result_json"])
            if (
                result.get("proposal", {}).get("needs_user_confirmation")
                and not result.get("review_result")
            ):
                pending.append(result)
        return pending

    def create_task_by_user(
        self,
        *,
        title: str,
        description: str | None = None,
        due_date: str | None = None,
        status: str = TaskStatus.TODO.value,
        reply_required: bool = False,
        importance: int | None = None,
    ) -> dict:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Task title is required")
        validated_status = TaskStatus(status)
        if validated_status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            raise ValueError("A new Task cannot start as completed or cancelled")
        if importance is not None and importance not in {1, 2, 3, 4}:
            raise ValueError("Task importance must be 1, 2, 3, 4 or None")
        now = _now()
        task_id = f"TASK-USER-{uuid4().hex[:10].upper()}"
        conversation_id = f"USER-CONVERSATION-{uuid4().hex[:10].upper()}"
        waiting_since = (
            now if validated_status == TaskStatus.WAITING_REPLY else None
        )
        with self.connect() as connection:
            try:
                connection.execute("BEGIN")
                connection.execute(
                    """
                    INSERT INTO tasks(task_id, conversation_id, title, requester,
                                      description, due_date, reply_required, status,
                                      waiting_since, importance_override, source_mail_id,
                                      created_at, updated_at)
                    VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 'USER-DASHBOARD', ?, ?)
                    """,
                    (
                        task_id,
                        conversation_id,
                        clean_title,
                        description.strip() if description else None,
                        due_date,
                        int(reply_required),
                        validated_status.value,
                        waiting_since,
                        importance,
                        now,
                        now,
                    ),
                )
                task = self._fetch_task(connection, task_id)
                connection.execute(
                    """
                    INSERT INTO histories(task_id, mail_id, action, before_json, after_json,
                                          reason, confidence, user_decision, created_at)
                    VALUES (?, 'USER-DASHBOARD', ?, NULL, ?, ?, 1.0, ?, ?)
                    """,
                    (
                        task_id,
                        AgentAction.CREATE_TASK.value,
                        _json(task),
                        "사용자가 Dashboard에서 업무를 직접 생성",
                        _json({"decision": "MANUAL_CREATE"}),
                        now,
                    ),
                )
                connection.commit()
                return task
            except Exception:
                connection.rollback()
                raise

    def update_task_by_user(
        self,
        task_id: str,
        *,
        title: str,
        description: str | None,
        due_date: str | None,
        status: str,
        reply_required: bool,
    ) -> dict:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Task title is required")
        validated_status = TaskStatus(status)
        now = _now()
        with self.connect() as connection:
            try:
                connection.execute("BEGIN")
                before = self._fetch_task(connection, task_id)
                if before is None:
                    raise ValueError(f"Task not found: {task_id}")
                validate_status_transition(before["status"], validated_status)
                waiting_since = before.get("waiting_since")
                if validated_status == TaskStatus.WAITING_REPLY and not waiting_since:
                    waiting_since = now
                elif validated_status != TaskStatus.WAITING_REPLY:
                    waiting_since = None
                connection.execute(
                    """
                    UPDATE tasks
                    SET title = ?, description = ?, due_date = ?, status = ?,
                        reply_required = ?, waiting_since = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (
                        clean_title,
                        description.strip() if description else None,
                        due_date,
                        validated_status.value,
                        int(reply_required),
                        waiting_since,
                        now,
                        task_id,
                    ),
                )
                after = self._fetch_task(connection, task_id)
                action = (
                    AgentAction.MARK_COMPLETED
                    if validated_status == TaskStatus.COMPLETED
                    else AgentAction.UPDATE_TASK
                )
                changed_fields = {
                    key: {"before": before.get(key), "after": after.get(key)}
                    for key in (
                        "title",
                        "description",
                        "due_date",
                        "status",
                        "reply_required",
                        "waiting_since",
                    )
                    if before.get(key) != after.get(key)
                }
                connection.execute(
                    """
                    INSERT INTO histories(task_id, mail_id, action, before_json, after_json,
                                          reason, confidence, user_decision, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        "USER-DASHBOARD",
                        action.value,
                        _json(before),
                        _json(after),
                        "사용자가 Dashboard에서 Task를 직접 수정",
                        1.0,
                        _json({"decision": "MANUAL_EDIT", "changes": changed_fields}),
                        now,
                    ),
                )
                connection.commit()
                return {
                    "task_id": task_id,
                    "action": action.value,
                    "before": before,
                    "after": after,
                    "changes": changed_fields,
                }
            except Exception:
                connection.rollback()
                raise

    def _fetch_task(self, connection: sqlite3.Connection, task_id: str) -> dict | None:
        row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["reply_required"] = bool(result["reply_required"])
        return result

    def list_tasks(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM tasks ORDER BY updated_at DESC").fetchall()
        result = [dict(row) for row in rows]
        for task in result:
            task["reply_required"] = bool(task["reply_required"])
        return result

    def set_task_importance(self, task_id: str, importance: int | None) -> dict:
        if importance is not None and importance not in {1, 2, 3, 4}:
            raise ValueError("Task importance must be 1, 2, 3, 4 or None")
        now = _now()
        with self.connect() as connection:
            try:
                connection.execute("BEGIN")
                before = self._fetch_task(connection, task_id)
                if before is None:
                    raise ValueError(f"Task not found: {task_id}")
                connection.execute(
                    "UPDATE tasks SET importance_override = ?, updated_at = ? WHERE task_id = ?",
                    (importance, now, task_id),
                )
                after = self._fetch_task(connection, task_id)
                connection.execute(
                    """
                    INSERT INTO histories(task_id, mail_id, action, before_json, after_json,
                                          reason, confidence, user_decision, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        "USER-DASHBOARD",
                        AgentAction.UPDATE_TASK.value,
                        _json(before),
                        _json(after),
                        "사용자가 Dashboard에서 Task 중요도를 직접 지정",
                        1.0,
                        _json(
                            {
                                "decision": "PRIORITY_OVERRIDE",
                                "importance": importance,
                            }
                        ),
                        now,
                    ),
                )
                connection.commit()
                return {"task_id": task_id, "before": before, "after": after}
            except Exception:
                connection.rollback()
                raise

    def list_priority_rules(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM priority_rules ORDER BY importance, rule_id"
            ).fetchall()
        rules = [dict(row) for row in rows]
        for rule in rules:
            rule["enabled"] = bool(rule["enabled"])
        return rules

    def list_mail_filter_rules(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM mail_filter_rules ORDER BY rule_id"
            ).fetchall()
        rules = [dict(row) for row in rows]
        for rule in rules:
            rule["enabled"] = bool(rule["enabled"])
        return rules

    def add_mail_filter_rule(
        self,
        *,
        name: str,
        rule_type: str,
        pattern: str,
    ) -> dict:
        clean_name = name.strip()
        clean_pattern = pattern.strip().casefold()
        if not clean_name or not clean_pattern:
            raise ValueError("Mail Filter Rule name and pattern are required")
        validated_type = MailFilterRuleType(rule_type)
        if validated_type == MailFilterRuleType.SENDER_DOMAIN:
            clean_pattern = clean_pattern.removeprefix("@")
        now = _now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO mail_filter_rules(name, rule_type, pattern, enabled, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (clean_name, validated_type.value, clean_pattern, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM mail_filter_rules WHERE rule_id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        return result

    def set_mail_filter_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE mail_filter_rules SET enabled = ? WHERE rule_id = ?",
                (int(enabled), rule_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Mail Filter Rule not found: {rule_id}")
            connection.commit()

    def delete_mail_filter_rule(self, rule_id: int) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM mail_filter_rules WHERE rule_id = ?", (rule_id,)
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Mail Filter Rule not found: {rule_id}")
            connection.commit()

    def add_priority_rule(
        self,
        *,
        name: str,
        rule_type: str,
        pattern: str,
        importance: int,
    ) -> dict:
        clean_name = name.strip()
        clean_pattern = pattern.strip().casefold()
        if not clean_name or not clean_pattern:
            raise ValueError("Priority Rule name and pattern are required")
        validated_type = PriorityRuleType(rule_type)
        if importance not in {1, 2, 3, 4}:
            raise ValueError("Priority Rule importance must be 1, 2, 3 or 4")
        if validated_type == PriorityRuleType.SENDER_DOMAIN:
            clean_pattern = clean_pattern.removeprefix("@")
        now = _now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO priority_rules(name, rule_type, pattern, importance, enabled, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (clean_name, validated_type.value, clean_pattern, importance, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM priority_rules WHERE rule_id = ?", (cursor.lastrowid,)
            ).fetchone()
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        return result

    def set_priority_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE priority_rules SET enabled = ? WHERE rule_id = ?",
                (int(enabled), rule_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Priority Rule not found: {rule_id}")
            connection.commit()

    def delete_priority_rule(self, rule_id: int) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM priority_rules WHERE rule_id = ?", (rule_id,)
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Priority Rule not found: {rule_id}")
            connection.commit()

    def get_priority_settings(self) -> dict[str, int]:
        defaults = {
            "due_soon_days": 3,
            "due_later_days": 7,
            "waiting_attention_days": 3,
        }
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT setting_key, setting_value FROM priority_settings"
            ).fetchall()
        return {**defaults, **{row["setting_key"]: int(row["setting_value"]) for row in rows}}

    def update_priority_settings(self, settings: dict[str, int]) -> dict[str, int]:
        allowed = {"due_soon_days", "due_later_days", "waiting_attention_days"}
        if set(settings) - allowed:
            raise ValueError("Unsupported Priority setting")
        resolved = self.get_priority_settings()
        resolved.update({key: int(value) for key, value in settings.items()})
        if not 1 <= resolved["due_soon_days"] < resolved["due_later_days"] <= 30:
            raise ValueError("Due thresholds must satisfy 1 <= soon < later <= 30")
        if not 1 <= resolved["waiting_attention_days"] <= 30:
            raise ValueError("Waiting threshold must be between 1 and 30 days")
        now = _now()
        with self.connect() as connection:
            for key, value in resolved.items():
                connection.execute(
                    """
                    INSERT INTO priority_settings(setting_key, setting_value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        setting_value = excluded.setting_value,
                        updated_at = excluded.updated_at
                    """,
                    (key, value, now),
                )
            connection.commit()
        return resolved

    def get_operation_settings(self) -> dict[str, bool | int]:
        defaults: dict[str, bool | int] = {
            "gmail_auto_sync_enabled": False,
            "gmail_sync_interval_minutes": 5,
        }
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT setting_key, setting_value FROM operation_settings"
            ).fetchall()
        stored = {row["setting_key"]: int(row["setting_value"]) for row in rows}
        return {
            **defaults,
            **stored,
            "gmail_auto_sync_enabled": bool(
                stored.get(
                    "gmail_auto_sync_enabled",
                    defaults["gmail_auto_sync_enabled"],
                )
            ),
        }

    def update_operation_settings(
        self,
        *,
        gmail_auto_sync_enabled: bool,
        gmail_sync_interval_minutes: int,
    ) -> dict[str, bool | int]:
        interval = int(gmail_sync_interval_minutes)
        if not 1 <= interval <= 60:
            raise ValueError("Gmail sync interval must be between 1 and 60 minutes")
        values = {
            "gmail_auto_sync_enabled": int(gmail_auto_sync_enabled),
            "gmail_sync_interval_minutes": interval,
        }
        now = _now()
        with self.connect() as connection:
            for key, value in values.items():
                connection.execute(
                    """
                    INSERT INTO operation_settings(setting_key, setting_value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        setting_value = excluded.setting_value,
                        updated_at = excluded.updated_at
                    """,
                    (key, value, now),
                )
            connection.commit()
        return self.get_operation_settings()

    def start_sync_run(self, *, run_id: str, source: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_runs(run_id, source, status, started_at)
                VALUES (?, ?, 'RUNNING', ?)
                """,
                (run_id, source, _now()),
            )
            connection.commit()

    def finish_sync_run(
        self,
        *,
        run_id: str,
        status: str,
        fetched_count: int,
        pending_count: int,
        succeeded_count: int,
        failed_count: int,
        duplicate_count: int,
        retry_count: int,
        error_type: str | None = None,
    ) -> None:
        allowed_statuses = {"SUCCESS", "PARTIAL", "FAILED"}
        if status not in allowed_statuses:
            raise ValueError(f"Unsupported sync status: {status}")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE sync_runs
                SET status = ?, fetched_count = ?, pending_count = ?,
                    succeeded_count = ?, failed_count = ?, duplicate_count = ?,
                    retry_count = ?, error_type = ?, finished_at = ?
                WHERE run_id = ? AND status = 'RUNNING'
                """,
                (
                    status,
                    int(fetched_count),
                    int(pending_count),
                    int(succeeded_count),
                    int(failed_count),
                    int(duplicate_count),
                    int(retry_count),
                    _sanitize(error_type),
                    _now(),
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Running sync not found: {run_id}")
            connection.commit()

    def list_sync_runs(self, *, source: str | None = None, limit: int = 20) -> list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError("Sync run limit must be between 1 and 200")
        query = "SELECT * FROM sync_runs"
        params: list[object] = []
        if source:
            query += " WHERE source = ?"
            params.append(source)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def backup_to(self, destination: Path) -> Path:
        self.initialize()
        resolved_source = self.path.resolve()
        resolved_destination = destination.resolve()
        if resolved_destination == resolved_source:
            raise ValueError("Backup destination must differ from the active database")
        resolved_destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source_connection:
            with sqlite3.connect(resolved_destination) as destination_connection:
                source_connection.backup(destination_connection)
        return resolved_destination

    def list_histories(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM histories ORDER BY history_id DESC"
            ).fetchall()
        return [dict(row) for row in rows]
