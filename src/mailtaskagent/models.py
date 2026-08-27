from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MailDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class AgentAction(StrEnum):
    CREATE_TASK = "CREATE_TASK"
    UPDATE_TASK = "UPDATE_TASK"
    LINK_TO_TASK = "LINK_TO_TASK"
    SET_WAITING = "SET_WAITING"
    MARK_COMPLETED = "MARK_COMPLETED"
    ASK_USER = "ASK_USER"
    IGNORE = "IGNORE"


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_REPLY = "WAITING_REPLY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewDecision(StrEnum):
    APPROVE_PROPOSAL = "APPROVE_PROPOSAL"
    LINK_EXISTING = "LINK_EXISTING"
    CREATE_NEW = "CREATE_NEW"
    IGNORE = "IGNORE"


class MailIntent(StrEnum):
    NEW_TASK = "NEW_TASK"
    DUE_DATE_CHANGE = "DUE_DATE_CHANGE"
    TASK_UPDATE = "TASK_UPDATE"
    WAITING = "WAITING"
    INFORMATION_RECEIVED = "INFORMATION_RECEIVED"
    COMPLETION = "COMPLETION"
    CANCELLATION = "CANCELLATION"
    NON_TASK = "NON_TASK"
    UNCERTAIN = "UNCERTAIN"


class MailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mail_id: str
    conversation_id: str
    direction: MailDirection
    sender: str
    recipients: list[str] = Field(default_factory=list)
    received_at: datetime | None = None
    sent_at: datetime | None = None
    subject: str
    body: str

    @model_validator(mode="after")
    def validate_direction_timestamp(self) -> "MailInput":
        if self.direction == MailDirection.INBOUND and self.received_at is None:
            raise ValueError("INBOUND mail requires received_at")
        if self.direction == MailDirection.OUTBOUND and self.sent_at is None:
            raise ValueError("OUTBOUND mail requires sent_at")
        return self

    @property
    def occurred_at(self) -> datetime:
        timestamp = self.received_at if self.direction == MailDirection.INBOUND else self.sent_at
        if timestamp is None:  # guarded by validation
            raise ValueError("Mail timestamp is missing")
        return timestamp


class MailAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_task_request: bool
    intent: MailIntent
    task_title: str | None = None
    request_summary: str | None = None
    requester: str | None = None
    due_date: date | None = None
    reply_required: bool = False
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class TaskCandidate(BaseModel):
    task_id: str
    conversation_id: str
    title: str
    requester: str | None = None
    description: str | None = None
    due_date: date | None = None
    reply_required: bool = False
    status: TaskStatus
    waiting_since: datetime | None = None
    match_score: float = Field(default=0, ge=0, le=1)
    match_reason: str = ""


class ActionProposal(BaseModel):
    action: AgentAction
    target_task_id: str | None = None
    task_payload: dict[str, Any] = Field(default_factory=dict)
    changes: dict[str, Any] = Field(default_factory=dict)
    reason: str
    confidence: float = Field(ge=0, le=1)
    needs_user_confirmation: bool = False


class WorkflowResult(BaseModel):
    case_id: str
    mail: MailInput
    analysis: MailAnalysis
    proposal: ActionProposal
    candidate_tasks: list[TaskCandidate] = Field(default_factory=list)
    task: dict[str, Any] | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    review_result: dict[str, Any] | None = None
    duplicate: bool = False
