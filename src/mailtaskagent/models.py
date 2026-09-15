from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HYPOTHESIS_ID_PATTERN = r"^H[1-3]$"
# Bounded so an over-long model response cannot break the trace log or the UI.
EvidenceText = Annotated[str, Field(min_length=1, max_length=300)]


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


class TaskRelation(StrEnum):
    SAME_TASK = "SAME_TASK"
    NEW_TASK = "NEW_TASK"
    AMBIGUOUS = "AMBIGUOUS"


class GuardVerdict(StrEnum):
    ACCEPTED = "ACCEPTED"
    ESCALATED = "ESCALATED"


class ReplyAction(StrEnum):
    NO_REPLY = "NO_REPLY"
    SIMPLE_ACK = "SIMPLE_ACK"
    DATE_REPLY = "DATE_REPLY"
    VALUE_REPLY = "VALUE_REPLY"
    APPROVE_REPLY = "APPROVE_REPLY"
    DRAFT_REPLY = "DRAFT_REPLY"
    ASK_USER = "ASK_USER"


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


class HypothesisDraft(BaseModel):
    """One candidate relation the generation Agent proposes.

    Carries no score: scoring belongs to the separate evaluation stage, otherwise
    the selection margin would only reflect the generator's own self-assessment.
    """

    model_config = ConfigDict(extra="forbid")

    relation: TaskRelation
    selected_task_id: str | None = None
    action: AgentAction
    supporting_evidence: list[EvidenceText] = Field(min_length=1, max_length=3)
    counter_evidence: list[EvidenceText] = Field(default_factory=list, max_length=2)
    risk: EvidenceText | None = None

    @field_validator("risk", mode="before")
    @classmethod
    def join_listed_risks(cls, value):
        """Accept the list the model tends to return for a field named `risk`.

        Its neighbours are lists, so a single-string field invites a list back.
        Joining is kinder than spending a retry on a difference that carries no
        meaning.
        """
        if isinstance(value, (list, tuple)):
            joined = " / ".join(str(item).strip() for item in value if str(item).strip())
            return joined or None
        return value


class HypothesisGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypotheses: list[HypothesisDraft] = Field(min_length=2, max_length=3)


class TaskHypothesis(HypothesisDraft):
    """A draft after Python assigned it a stable id."""

    hypothesis_id: str = Field(pattern=HYPOTHESIS_ID_PATTERN)


class HypothesisEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(pattern=HYPOTHESIS_ID_PATTERN)
    support_score: float = Field(ge=0, le=1)
    evaluation_reason: str = Field(min_length=1, max_length=500)


class HypothesisSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluations: list[HypothesisEvaluation] = Field(min_length=2, max_length=3)
    selected_hypothesis_id: str = Field(pattern=HYPOTHESIS_ID_PATTERN)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)
    rewritten_query: str | None = Field(default=None, max_length=300)


class ContractViolation(StrEnum):
    OUTSIDE_CANDIDATE = "OUTSIDE_CANDIDATE"
    INVALID_RELATION_ACTION = "INVALID_RELATION_ACTION"
    MISSING_TASK_ID = "MISSING_TASK_ID"
    DUPLICATE_HYPOTHESIS = "DUPLICATE_HYPOTHESIS"
    INCOMPLETE_EVALUATION = "INCOMPLETE_EVALUATION"
    UNKNOWN_HYPOTHESIS = "UNKNOWN_HYPOTHESIS"
    SELECTION_SCORE_MISMATCH = "SELECTION_SCORE_MISMATCH"
    TOO_FEW_HYPOTHESES = "TOO_FEW_HYPOTHESES"
    # The response never reached the contract checks: malformed JSON or a body
    # the schema rejected. Recorded as a code so no raw model output is stored.
    SCHEMA_INVALID = "SCHEMA_INVALID"


class RejectedHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str | None = None
    violation: ContractViolation


class TaskContextDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation: TaskRelation
    selected_task_id: str | None = None
    recommended_action: AgentAction
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    rewritten_query: str | None = None
    hypotheses: list[TaskHypothesis] = Field(default_factory=list, max_length=3)
    selection_margin: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_relation_contract(self) -> "TaskContextDecision":
        if self.relation == TaskRelation.SAME_TASK and not self.selected_task_id:
            raise ValueError("SAME_TASK requires selected_task_id")
        if self.rewritten_query is not None:
            self.rewritten_query = self.rewritten_query.strip() or None
        if self.hypotheses:
            chosen = (self.relation, self.selected_task_id, self.recommended_action)
            if not any(
                (item.relation, item.selected_task_id, item.action) == chosen
                for item in self.hypotheses
            ):
                raise ValueError("decision does not match any generated hypothesis")
        return self


class TaskContextAgentResult(BaseModel):
    """Everything the workflow needs to trace a two-stage deliberation.

    The decision alone would lose the rejected candidates, the per-stage retries
    and the timings, so the generation and evaluation events could not be written.
    """

    model_config = ConfigDict(extra="forbid")

    decision: TaskContextDecision
    generated_hypotheses: list[TaskHypothesis] = Field(default_factory=list)
    evaluations: list[HypothesisEvaluation] = Field(default_factory=list)
    rejected_hypotheses: list[RejectedHypothesis] = Field(default_factory=list)
    generation_schema_retries: int = 0
    evaluation_schema_retries: int = 0
    application_llm_call_count: int = 0
    generation_duration_ms: int = 0
    evaluation_duration_ms: int = 0
    total_duration_ms: int = 0
    is_redecision: bool = False


class GuardedActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: GuardVerdict
    agent_action: AgentAction
    final_proposal: ActionProposal
    reason: str = Field(min_length=1)


class ReplyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReplyAction
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    question: str | None = None
    draft_body: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_reply_contract(self) -> "ReplyPlan":
        self.question = self.question.strip() if self.question else None
        self.draft_body = self.draft_body.strip() if self.draft_body else None
        needs_input = {
            ReplyAction.DATE_REPLY,
            ReplyAction.VALUE_REPLY,
            ReplyAction.APPROVE_REPLY,
        }
        if self.action in needs_input and not self.question:
            raise ValueError(f"{self.action.value} requires a user question")
        if self.action in {ReplyAction.SIMPLE_ACK, ReplyAction.DRAFT_REPLY} and not self.draft_body:
            raise ValueError(f"{self.action.value} requires draft_body")
        if self.action in {ReplyAction.NO_REPLY, ReplyAction.ASK_USER} and self.draft_body:
            raise ValueError(f"{self.action.value} must not create a draft")
        return self


class ReplyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReplyAction
    body: str = Field(min_length=1, max_length=4000)
    user_input: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def normalize_reply_draft(self) -> "ReplyDraft":
        self.body = self.body.strip()
        self.user_input = self.user_input.strip() if self.user_input else None
        if not self.body:
            raise ValueError("Reply draft body must not be blank")
        return self


class WorkflowResult(BaseModel):
    case_id: str
    mail: MailInput
    analysis: MailAnalysis
    proposal: ActionProposal
    thread_history: list[dict[str, Any]] = Field(default_factory=list)
    candidate_tasks: list[TaskCandidate] = Field(default_factory=list)
    current_task_context: dict[str, Any] | None = None
    retrieval_query: str | None = None
    retrieved_task_contexts: list[dict[str, Any]] = Field(default_factory=list)
    task_context_decision: TaskContextDecision | None = None
    guard_result: GuardedActionResult | None = None
    rag_retry_count: int = 0
    match_route: str = "LEGACY"
    validation_result: dict[str, Any] = Field(default_factory=dict)
    task: dict[str, Any] | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    review_result: dict[str, Any] | None = None
    duplicate: bool = False
