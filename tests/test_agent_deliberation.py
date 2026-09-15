"""Workflow-level contracts for bounded multi-hypothesis deliberation."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from mailtaskagent.config import Settings
from mailtaskagent.models import (
    AgentAction,
    ContractViolation,
    GuardVerdict,
    HypothesisDraft,
    HypothesisEvaluation,
    HypothesisGeneration,
    MailAnalysis,
    MailDirection,
    MailInput,
    MailIntent,
    TaskContextAgentResult,
    TaskContextDecision,
    TaskRelation,
)
from mailtaskagent.deliberation import assign_hypothesis_ids
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.task_context_agent import (
    AzureTaskContextAgent,
    DeliberationContractFailure,
)
from mailtaskagent.workflow import MailTaskWorkflow


class _StaticAnalyzer:
    def __init__(self, analysis: MailAnalysis):
        self.analysis = analysis

    def analyze(self, mail: MailInput) -> MailAnalysis:
        return self.analysis


def _mail(mail_id: str, conversation_id: str, *, subject: str, body: str) -> MailInput:
    return MailInput(
        mail_id=mail_id,
        conversation_id=conversation_id,
        direction=MailDirection.INBOUND,
        sender="owner@example.test",
        recipients=["worker@example.test"],
        received_at=datetime(2026, 9, 2, 9, tzinfo=UTC),
        subject=subject,
        body=body,
    )


def _analysis(intent: MailIntent, *, title: str | None, summary: str) -> MailAnalysis:
    return MailAnalysis(
        is_task_request=True,
        intent=intent,
        task_title=title,
        request_summary=summary,
        requester="owner@example.test",
        due_date=date(2026, 9, 10),
        reply_required=True,
        reason="합성 Deliberation 검증 입력",
        confidence=0.94,
    )


@pytest.fixture
def base_settings(tmp_path: Path) -> Settings:
    return Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=tmp_path / "deliberation.db",
        confidence_threshold=0.75,
    )


def _rag_settings(settings: Settings, **overrides) -> Settings:
    return replace(
        settings,
        task_context_rag_enabled=True,
        task_context_rag_top_k=5,
        task_context_rag_confidence_threshold=0.75,
        task_context_rag_max_retries=1,
        **overrides,
    )


def _seed_task(settings: Settings, storage: SQLiteStorage) -> dict:
    result = MailTaskWorkflow(
        settings,
        storage,
        _StaticAnalyzer(
            _analysis(
                MailIntent.NEW_TASK,
                title="접근통제 서버 장애 영향도 점검",
                summary="접근통제 장애 영향을 점검하고 결과를 공유한다.",
            )
        ),
    ).process(
        _mail(
            "DLB-SEED",
            "THREAD-SEED",
            subject="접근통제 서버 장애 영향도 점검",
            body="장애 영향을 점검하고 결과를 공유해 주세요.",
        )
    )
    assert result.task is not None
    return result.task


def _followup(settings, storage, agent):
    return MailTaskWorkflow(
        settings,
        storage,
        _StaticAnalyzer(
            _analysis(
                MailIntent.TASK_UPDATE,
                title=None,
                summary="장애 분석 자료를 반영해 최종 결과를 공유한다.",
            )
        ),
        task_context_agent=agent,
    ).process(
        _mail(
            "DLB-FOLLOWUP",
            "THREAD-OTHER",
            subject="지난 건 마무리 요청",
            body="앞서 논의한 내용을 반영해 마무리해 주세요.",
        )
    )


def _hypotheses(task_id: str):
    return assign_hypothesis_ids(
        HypothesisGeneration(
            hypotheses=[
                HypothesisDraft(
                    relation=TaskRelation.SAME_TASK,
                    selected_task_id=task_id,
                    action=AgentAction.UPDATE_TASK,
                    supporting_evidence=["요청자와 대상 시스템이 일치"],
                    counter_evidence=["Thread가 다름"],
                    risk="다른 업무를 잘못 갱신할 수 있음",
                ),
                HypothesisDraft(
                    relation=TaskRelation.NEW_TASK,
                    action=AgentAction.CREATE_TASK,
                    supporting_evidence=["제목이 기존 업무와 다름"],
                ),
            ]
        )
    )


class _DeliberatingAgent:
    """Returns the full two-stage result, like the production agents do."""

    def __init__(self, task_id: str, scores: tuple[float, float], *, confidence: float = 0.91):
        self.task_id = task_id
        self.scores = scores
        self.confidence = confidence
        self.calls = 0

    def judge(self, current_mail, mail_analysis, retrieved_task_contexts, *, retry_count):
        self.calls += 1
        hypotheses = _hypotheses(self.task_id)
        evaluations = [
            HypothesisEvaluation(
                hypothesis_id=item.hypothesis_id,
                support_score=score,
                evaluation_reason="다른 가설과 비교한 근거",
            )
            for item, score in zip(hypotheses, self.scores)
        ]
        margin = round(abs(self.scores[0] - self.scores[1]), 6)
        winner = hypotheses[0]
        return TaskContextAgentResult(
            decision=TaskContextDecision(
                relation=winner.relation,
                selected_task_id=winner.selected_task_id,
                recommended_action=winner.action,
                confidence=self.confidence,
                reason="평가 단계가 상위 가설을 선택",
                rewritten_query="접근통제 장애 영향도 최종 결과" if retry_count == 0 else None,
                hypotheses=hypotheses,
                selection_margin=margin,
            ),
            generated_hypotheses=hypotheses,
            evaluations=evaluations,
            application_llm_call_count=2,
            generation_duration_ms=11,
            evaluation_duration_ms=13,
            total_duration_ms=24,
            is_redecision=retry_count > 0,
        )


class _NarrowThenWideAgent(_DeliberatingAgent):
    """Tied on the first pass, decisive after the query rewrite."""

    def judge(self, current_mail, mail_analysis, retrieved_task_contexts, *, retry_count):
        self.scores = (0.60, 0.58) if retry_count == 0 else (0.88, 0.30)
        return super().judge(
            current_mail, mail_analysis, retrieved_task_contexts, retry_count=retry_count
        )


def _steps(storage: SQLiteStorage) -> list[str]:
    return [event["step"] for event in storage.list_events()]


def _details(storage: SQLiteStorage, step: str) -> dict:
    for event in storage.list_events():
        if event["step"] == step:
            return json.loads(event["details_json"])
    raise AssertionError(f"event not found: {step}")


def test_wide_margin_executes_and_records_both_stages(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    task = _seed_task(base_settings, storage)
    agent = _DeliberatingAgent(task["task_id"], (0.88, 0.30))

    result = _followup(_rag_settings(base_settings), storage, agent)

    assert result.match_route == "STRUCTURED_RAG"
    assert result.guard_result is not None
    assert result.guard_result.verdict is GuardVerdict.ACCEPTED
    assert result.proposal.action is AgentAction.UPDATE_TASK

    steps = _steps(storage)
    for step in (
        "M-03 HYPOTHESIS_GENERATION",
        "M-03 HYPOTHESIS_VALIDATION",
        "M-03 HYPOTHESIS_EVALUATION",
        "M-03 DELIBERATION_DECISION",
    ):
        assert step in steps

    decision = _details(storage, "M-03 DELIBERATION_DECISION")
    assert decision["selection_margin"] == pytest.approx(0.58)
    assert decision["application_llm_call_count"] == 2


def test_generation_event_keeps_evidence_and_no_raw_response(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    task = _seed_task(base_settings, storage)
    _followup(_rag_settings(base_settings), storage, _DeliberatingAgent(task["task_id"], (0.88, 0.30)))

    generation = _details(storage, "M-03 HYPOTHESIS_GENERATION")
    assert [item["hypothesis_id"] for item in generation["hypotheses"]] == ["H1", "H2"]
    assert generation["hypotheses"][0]["supporting_evidence"]
    assert generation["hypotheses"][0]["counter_evidence"]
    assert "raw" not in generation and "content" not in generation

    evaluation = _details(storage, "M-03 HYPOTHESIS_EVALUATION")
    assert {item["hypothesis_id"] for item in evaluation["evaluations"]} == {"H1", "H2"}
    assert all(item["evaluation_reason"] for item in evaluation["evaluations"])


def test_narrow_margin_triggers_one_query_rewrite(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    task = _seed_task(base_settings, storage)
    agent = _NarrowThenWideAgent(task["task_id"], (0.60, 0.58))

    result = _followup(_rag_settings(base_settings), storage, agent)

    assert agent.calls == 2
    assert result.rag_retry_count == 1
    assert result.proposal.action is AgentAction.UPDATE_TASK
    steps = _steps(storage)
    assert "M-03 QUERY_REWRITE" in steps
    assert "M-03 HYPOTHESIS_REGENERATION" in steps
    assert "M-03 HYPOTHESIS_REEVALUATION" in steps
    assert "M-03 DELIBERATION_REDECISION" in steps


def test_narrow_margin_after_retry_fails_closed(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    task = _seed_task(base_settings, storage)
    before = storage.get_task(task["task_id"])
    agent = _DeliberatingAgent(task["task_id"], (0.60, 0.58))

    result = _followup(_rag_settings(base_settings), storage, agent)

    assert result.proposal.action is AgentAction.ASK_USER
    assert result.proposal.needs_user_confirmation is True
    assert "차이가" in result.proposal.reason
    assert storage.get_task(task["task_id"]) == before
    assert len(storage.list_pending_reviews()) == 1


def test_margin_threshold_is_configurable(base_settings: Settings) -> None:
    storage = SQLiteStorage(base_settings.database_path)
    task = _seed_task(base_settings, storage)
    settings = _rag_settings(base_settings, agent_deliberation_min_margin=0.01)

    result = _followup(settings, storage, _DeliberatingAgent(task["task_id"], (0.60, 0.58)))

    assert result.proposal.action is AgentAction.UPDATE_TASK


def test_decision_not_matching_any_hypothesis_is_rejected(base_settings: Settings) -> None:
    hypotheses = _hypotheses("TASK-001")
    with pytest.raises(ValueError, match="does not match any generated hypothesis"):
        TaskContextDecision(
            relation=TaskRelation.SAME_TASK,
            selected_task_id="TASK-001",
            recommended_action=AgentAction.MARK_COMPLETED,
            confidence=0.9,
            reason="가설에 없는 Action",
            hypotheses=hypotheses,
        )


def test_legacy_agent_without_hypotheses_still_works(base_settings: Settings) -> None:
    """The bare-decision stubs must keep exercising the guard path."""

    class _BareAgent:
        def __init__(self, task_id: str):
            self.task_id = task_id

        def judge(self, current_mail, mail_analysis, retrieved_task_contexts, *, retry_count):
            return TaskContextDecision(
                relation=TaskRelation.SAME_TASK,
                selected_task_id=self.task_id,
                recommended_action=AgentAction.UPDATE_TASK,
                confidence=0.93,
                reason="단일 결론 경로",
            )

    storage = SQLiteStorage(base_settings.database_path)
    task = _seed_task(base_settings, storage)

    result = _followup(_rag_settings(base_settings), storage, _BareAgent(task["task_id"]))

    assert result.proposal.action is AgentAction.UPDATE_TASK
    assert "M-03 HYPOTHESIS_GENERATION" not in _steps(storage)


def test_high_risk_gate_survives_a_wide_margin(base_settings: Settings) -> None:
    """A confident, well-separated completion still needs the user."""
    storage = SQLiteStorage(base_settings.database_path)
    task = _seed_task(base_settings, storage)

    class _CompletionAgent(_DeliberatingAgent):
        def judge(self, current_mail, mail_analysis, retrieved_task_contexts, *, retry_count):
            hypotheses = assign_hypothesis_ids(
                HypothesisGeneration(
                    hypotheses=[
                        HypothesisDraft(
                            relation=TaskRelation.SAME_TASK,
                            selected_task_id=self.task_id,
                            action=AgentAction.MARK_COMPLETED,
                            supporting_evidence=["완료를 알리는 메일"],
                        ),
                        HypothesisDraft(
                            relation=TaskRelation.AMBIGUOUS,
                            action=AgentAction.ASK_USER,
                            supporting_evidence=["완료 범위가 불명확할 수 있음"],
                        ),
                    ]
                )
            )
            return TaskContextAgentResult(
                decision=TaskContextDecision(
                    relation=TaskRelation.SAME_TASK,
                    selected_task_id=self.task_id,
                    recommended_action=AgentAction.MARK_COMPLETED,
                    confidence=0.99,
                    reason="완료 판단",
                    hypotheses=hypotheses,
                    selection_margin=0.7,
                ),
                generated_hypotheses=hypotheses,
                evaluations=[
                    HypothesisEvaluation(
                        hypothesis_id="H1", support_score=0.95, evaluation_reason="a"
                    ),
                    HypothesisEvaluation(
                        hypothesis_id="H2", support_score=0.25, evaluation_reason="b"
                    ),
                ],
            )

    result = MailTaskWorkflow(
        _rag_settings(base_settings),
        storage,
        _StaticAnalyzer(
            _analysis(MailIntent.COMPLETION, title=None, summary="점검을 완료했습니다.")
        ),
        task_context_agent=_CompletionAgent(task["task_id"], (0.95, 0.25)),
    ).process(
        _mail("DLB-DONE", "THREAD-OTHER", subject="점검 완료", body="완료했습니다.")
    )

    assert result.proposal.needs_user_confirmation is True
    assert storage.get_task(task["task_id"])["status"] == "TODO"


def _azure_agent(settings: Settings, bodies: list[str]) -> tuple[AzureTaskContextAgent, list]:
    agent = AzureTaskContextAgent(replace(settings, api_key="test-key", use_mock=False))
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        content = bodies[min(len(calls) - 1, len(bodies) - 1)]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    agent.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return agent, calls


def test_task_context_agent_disables_sdk_retries_for_shared_deadline(
    base_settings: Settings,
) -> None:
    agent = AzureTaskContextAgent(
        replace(base_settings, api_key="test-key", use_mock=False)
    )

    assert agent.client.max_retries == 0


_GOOD_GENERATION = json.dumps(
    {
        "hypotheses": [
            {
                "relation": "SAME_TASK",
                "selected_task_id": "TASK-001",
                "action": "UPDATE_TASK",
                "supporting_evidence": ["요청자와 대상이 일치"],
                "counter_evidence": [],
                "risk": None,
            },
            {
                "relation": "NEW_TASK",
                "selected_task_id": None,
                "action": "CREATE_TASK",
                "supporting_evidence": ["제목이 다름"],
                "counter_evidence": [],
                "risk": None,
            },
        ]
    },
    ensure_ascii=False,
)

_GOOD_SELECTION = json.dumps(
    {
        "evaluations": [
            {"hypothesis_id": "H1", "support_score": 0.86, "evaluation_reason": "근거가 더 강함"},
            {"hypothesis_id": "H2", "support_score": 0.22, "evaluation_reason": "신규로 보기 어려움"},
        ],
        "selected_hypothesis_id": "H1",
        "confidence": 0.9,
        "reason": "동일 업무의 갱신",
        "rewritten_query": None,
    },
    ensure_ascii=False,
)

_CONTEXTS = [
    {
        "candidate": {"task_id": "TASK-001", "status": "TODO", "match_score": 0.8},
        "recent_mails": [],
        "recent_histories": [],
        "retrieval_reasons": [],
    }
]


def _judge_args():
    return (
        _mail("DLB-LIVE", "THREAD-LIVE", subject="후속", body="후속 요청"),
        _analysis(MailIntent.TASK_UPDATE, title=None, summary="후속 요청"),
        _CONTEXTS,
    )


def test_live_agent_runs_two_stages_and_computes_margin(base_settings: Settings) -> None:
    agent, calls = _azure_agent(base_settings, [_GOOD_GENERATION, _GOOD_SELECTION])

    result = agent.judge(*_judge_args(), retry_count=0)

    assert len(calls) == 2
    assert result.application_llm_call_count == 2
    assert result.decision.selection_margin == pytest.approx(0.64)
    assert result.decision.selected_task_id == "TASK-001"
    # The generated ids are ours, never the model's.
    assert [item.hypothesis_id for item in result.generated_hypotheses] == ["H1", "H2"]


def test_live_agent_retries_a_broken_generation_body(base_settings: Settings) -> None:
    agent, calls = _azure_agent(
        base_settings, ["{not json", _GOOD_GENERATION, _GOOD_SELECTION]
    )

    result = agent.judge(*_judge_args(), retry_count=0)

    assert len(calls) == 3
    assert result.generation_schema_retries == 1
    assert result.application_llm_call_count == 3


def test_live_agent_gives_up_after_repeated_contract_breaches(base_settings: Settings) -> None:
    outside_candidate = json.dumps(
        {
            "hypotheses": [
                {
                    "relation": "SAME_TASK",
                    "selected_task_id": "TASK-999",
                    "action": "UPDATE_TASK",
                    "supporting_evidence": ["검색 결과에 없는 Task"],
                    "counter_evidence": [],
                    "risk": None,
                },
                {
                    "relation": "NEW_TASK",
                    "selected_task_id": None,
                    "action": "CREATE_TASK",
                    "supporting_evidence": ["제목이 다름"],
                    "counter_evidence": [],
                    "risk": None,
                },
            ]
        },
        ensure_ascii=False,
    )
    agent, _ = _azure_agent(base_settings, [outside_candidate])

    with pytest.raises(Exception) as excinfo:
        agent.judge(*_judge_args(), retry_count=0)

    assert "OUTSIDE_CANDIDATE" in str(excinfo.value)


class _Clock:
    """A clock the test moves on purpose.

    Pinning monotonic to a fixed list of ticks made the test depend on how many
    times the agent happens to read the clock, which changed the moment the
    budget became a shared deadline.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_live_agent_stops_when_the_time_budget_is_gone(
    base_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent, calls = _azure_agent(base_settings, [_GOOD_GENERATION, _GOOD_SELECTION])
    clock = _Clock()
    monkeypatch.setattr("mailtaskagent.task_context_agent.time.monotonic", clock)

    original = agent.client.chat.completions.create

    def burn_the_budget(*args, **kwargs):
        response = original(*args, **kwargs)
        clock.advance(base_settings.agent_deliberation_budget_ms / 1000 + 1)
        return response

    agent.client.chat.completions.create = burn_the_budget

    with pytest.raises(TimeoutError, match="budget"):
        agent.judge(*_judge_args(), retry_count=0)

    assert len(calls) == 1, "the evaluation call must not be made after the budget is gone"


def test_the_budget_is_not_refreshed_by_a_second_judgement(
    base_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A query rewrite must not buy another full budget.

    The budget used to restart inside every judge() call, so a mail that went
    around the rewrite loop could spend it twice over.
    """
    agent, calls = _azure_agent(
        base_settings,
        [_GOOD_GENERATION, _GOOD_SELECTION, _GOOD_GENERATION, _GOOD_SELECTION],
    )
    clock = _Clock()
    monkeypatch.setattr("mailtaskagent.task_context_agent.time.monotonic", clock)

    agent.start_deliberation_budget()
    agent.judge(*_judge_args(), retry_count=0)
    assert len(calls) == 2

    # Most of the budget is gone by the time the rewrite comes back.
    clock.advance(base_settings.agent_deliberation_budget_ms / 1000 + 1)

    with pytest.raises(TimeoutError, match="budget"):
        agent.judge(*_judge_args(), retry_count=1)

    assert len(calls) == 2, "the re-judgement must not call the model on an expired budget"


def test_each_request_is_capped_by_the_time_left(
    base_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single call cannot be given longer than the budget still allows."""
    agent, calls = _azure_agent(base_settings, [_GOOD_GENERATION, _GOOD_SELECTION])
    clock = _Clock()
    monkeypatch.setattr("mailtaskagent.task_context_agent.time.monotonic", clock)

    timeouts: list[float] = []
    original = agent.client.chat.completions.create
    budget_seconds = base_settings.agent_deliberation_budget_ms / 1000
    # Leave the second call less than one per-request timeout of budget, so the
    # cap has to come from the deadline rather than from timeout_seconds.
    remaining_after_first = base_settings.timeout_seconds / 2
    burn = budget_seconds - remaining_after_first

    def record_timeout(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        response = original(*args, **kwargs)
        if len(timeouts) == 1:
            # Only the first call is slow; the second must still fit in what is
            # left rather than getting a fresh per-request timeout.
            clock.advance(burn)
        return response

    agent.client.chat.completions.create = record_timeout

    agent.start_deliberation_budget()
    agent.judge(*_judge_args(), retry_count=0)

    assert len(timeouts) == 2
    assert timeouts[0] == base_settings.timeout_seconds
    assert timeouts[1] < base_settings.timeout_seconds, (
        "the second request should get only the time the first one left"
    )
    assert timeouts[1] == pytest.approx(remaining_after_first, abs=0.01)


_LISTED_RISK_GENERATION = json.dumps(
    {
        "hypotheses": [
            {
                "relation": "SAME_TASK",
                "selected_task_id": "TASK-001",
                "action": "UPDATE_TASK",
                "supporting_evidence": ["요청자와 대상이 일치"],
                "counter_evidence": [],
                "risk": ["잘못된 업무를 갱신할 수 있음", "요청자가 다를 수 있음"],
            },
            {
                "relation": "NEW_TASK",
                "selected_task_id": None,
                "action": "CREATE_TASK",
                "supporting_evidence": ["제목이 다름"],
                "counter_evidence": [],
                "risk": None,
            },
        ]
    },
    ensure_ascii=False,
)

_OUTSIDE_CANDIDATE_GENERATION = json.dumps(
    {
        "hypotheses": [
            {
                "relation": "SAME_TASK",
                "selected_task_id": "TASK-999",
                "action": "UPDATE_TASK",
                "supporting_evidence": ["검색 결과에 없는 Task"],
                "counter_evidence": [],
                "risk": None,
            },
            {
                "relation": "NEW_TASK",
                "selected_task_id": None,
                "action": "CREATE_TASK",
                "supporting_evidence": ["제목이 다름"],
                "counter_evidence": [],
                "risk": None,
            },
        ]
    },
    ensure_ascii=False,
)


def test_a_listed_risk_is_joined_rather_than_costing_a_retry(
    base_settings: Settings,
) -> None:
    """The model returns a list for `risk` because its neighbours are lists."""
    agent, calls = _azure_agent(base_settings, [_LISTED_RISK_GENERATION, _GOOD_SELECTION])

    result = agent.judge(*_judge_args(), retry_count=0)

    assert len(calls) == 2
    assert result.generation_schema_retries == 0
    assert result.generated_hypotheses[0].risk == (
        "잘못된 업무를 갱신할 수 있음 / 요청자가 다를 수 있음"
    )


def test_a_contract_breach_is_retried_before_failing_closed(
    base_settings: Settings,
) -> None:
    """A broken contract must reach the correction attempt.

    Validating outside the retry loop meant these went straight to the
    fail-closed path, so a single bad field cost the whole decision.
    """
    agent, calls = _azure_agent(
        base_settings,
        [_OUTSIDE_CANDIDATE_GENERATION, _GOOD_GENERATION, _GOOD_SELECTION],
    )

    result = agent.judge(*_judge_args(), retry_count=0)

    assert len(calls) == 3
    assert result.generation_schema_retries == 1
    assert result.decision.selected_task_id == "TASK-001"


def test_a_broken_evaluation_contract_is_also_retried(base_settings: Settings) -> None:
    incomplete = json.dumps(
        {
            "evaluations": [
                {"hypothesis_id": "H1", "support_score": 0.9, "evaluation_reason": "a"},
                {"hypothesis_id": "H1", "support_score": 0.2, "evaluation_reason": "b"},
            ],
            "selected_hypothesis_id": "H1",
            "confidence": 0.9,
            "reason": "H2를 평가하지 않음",
            "rewritten_query": None,
        },
        ensure_ascii=False,
    )
    agent, calls = _azure_agent(
        base_settings, [_GOOD_GENERATION, incomplete, _GOOD_SELECTION]
    )

    result = agent.judge(*_judge_args(), retry_count=0)

    assert len(calls) == 3
    assert result.evaluation_schema_retries == 1


def test_a_corrected_retry_still_records_what_the_first_attempt_broke(
    base_settings: Settings,
) -> None:
    """The violation trace used to be empty whenever the retry succeeded.

    rejected_hypotheses existed on the result and the workflow wrote it into the
    event, but nothing ever assigned it, so a judgement that only worked on the
    second attempt looked as though the first had been fine.
    """
    agent, calls = _azure_agent(
        base_settings,
        [_OUTSIDE_CANDIDATE_GENERATION, _GOOD_GENERATION, _GOOD_SELECTION],
    )

    result = agent.judge(*_judge_args(), retry_count=0)

    assert len(calls) == 3, "the first generation should have been retried"
    assert result.generation_schema_retries == 1
    violations = {item.violation for item in result.rejected_hypotheses}
    assert ContractViolation.OUTSIDE_CANDIDATE in violations, (
        "the corrected attempt must still show what the first response broke"
    )


def test_a_final_contract_failure_carries_codes_not_model_text(
    base_settings: Settings,
) -> None:
    """Nothing that can quote the model's input may reach the trace."""
    agent, _ = _azure_agent(base_settings, [_OUTSIDE_CANDIDATE_GENERATION])

    with pytest.raises(DeliberationContractFailure) as excinfo:
        agent.judge(*_judge_args(), retry_count=0)

    failure = excinfo.value
    assert {item.violation for item in failure.violations} == {
        ContractViolation.OUTSIDE_CANDIDATE
    }
    message = str(failure)
    assert "OUTSIDE_CANDIDATE" in message
    assert "TASK-999" not in message, "the offending value must not appear in the message"
    assert "supporting_evidence" not in message, "no part of the response may leak"
