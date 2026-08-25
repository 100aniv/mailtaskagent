from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from mailtaskagent.models import (
    ActionProposal,
    AgentAction,
    MailAnalysis,
    MailInput,
    ReviewDecision,
    TaskCandidate,
    TaskStatus,
)


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
            if any(secret in normalized for secret in ("api_key", "authorization", "token", "secret")):
                result[key] = "[REDACTED]"
            else:
                result[key] = _sanitize(item)
        return result
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        redacted = re.sub(r"atl-[A-Za-z0-9._-]+", "[REDACTED]", value, flags=re.IGNORECASE)
        redacted = re.sub(
            r"(?i)(api[-_ ]?key|authorization)(\s*[:=]\s*)([^\s,;]+)",
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
            connection.commit()

    def reset(self) -> None:
        self.initialize()
        with self.connect() as connection:
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
                return [self._candidate_from_row(row) for row in exact_rows[:limit]]
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
            score = len(query_tokens & candidate_tokens)
            if score:
                ranked.append((score, candidate))
        ranked.sort(key=lambda item: (-item[0], item[1].task_id))
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
                    "candidate_tasks": [item.model_dump(mode="json") for item in candidate_tasks],
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
                        if before["status"] in {
                            TaskStatus.COMPLETED.value,
                            TaskStatus.CANCELLED.value,
                        }:
                            raise ValueError(f"Task cannot be completed from {before['status']}")
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
                        if before["status"] in {
                            TaskStatus.COMPLETED.value,
                            TaskStatus.CANCELLED.value,
                        }:
                            raise ValueError(f"Task cannot be cancelled from {before['status']}")
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

    def list_histories(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM histories ORDER BY history_id DESC"
            ).fetchall()
        return [dict(row) for row in rows]
