from __future__ import annotations

import pytest

from mailtaskagent.deliberation import (
    HypothesisContractError,
    assign_hypothesis_ids,
    selection_margin,
    validate_generation,
    validate_selection,
)
from mailtaskagent.models import (
    AgentAction,
    ContractViolation,
    HypothesisDraft,
    HypothesisEvaluation,
    HypothesisGeneration,
    HypothesisSelection,
    TaskHypothesis,
    TaskRelation,
)

CANDIDATE_IDS = ["TASK-001", "TASK-002"]


def _draft(
    relation: TaskRelation,
    action: AgentAction,
    task_id: str | None = None,
    evidence: str = "근거",
) -> HypothesisDraft:
    return HypothesisDraft(
        relation=relation,
        selected_task_id=task_id,
        action=action,
        supporting_evidence=[evidence],
    )


def _same(task_id: str = "TASK-001", action: AgentAction = AgentAction.UPDATE_TASK):
    return _draft(TaskRelation.SAME_TASK, action, task_id, f"{task_id} 근거")


def _new():
    return _draft(TaskRelation.NEW_TASK, AgentAction.CREATE_TASK)


def _ambiguous():
    return _draft(TaskRelation.AMBIGUOUS, AgentAction.ASK_USER)


def _ids(drafts: list[HypothesisDraft]):
    return assign_hypothesis_ids(HypothesisGeneration(hypotheses=drafts))


def _violations(excinfo) -> set[ContractViolation]:
    return {item.violation for item in excinfo.value.violations}


def test_python_assigns_hypothesis_ids_in_order() -> None:
    hypotheses = _ids([_same(), _new(), _ambiguous()])
    assert [item.hypothesis_id for item in hypotheses] == ["H1", "H2", "H3"]


def test_valid_generation_passes() -> None:
    validate_generation(_ids([_same(), _new()]), CANDIDATE_IDS)


def test_task_id_outside_retrieved_candidates_fails_whole_response() -> None:
    hypotheses = _ids([_same(), _new(), _same("TASK-999")])
    with pytest.raises(HypothesisContractError) as excinfo:
        validate_generation(hypotheses, CANDIDATE_IDS)
    assert ContractViolation.OUTSIDE_CANDIDATE in _violations(excinfo)


def test_same_task_without_task_id_is_rejected() -> None:
    hypotheses = _ids([_draft(TaskRelation.SAME_TASK, AgentAction.UPDATE_TASK), _new()])
    with pytest.raises(HypothesisContractError) as excinfo:
        validate_generation(hypotheses, CANDIDATE_IDS)
    assert ContractViolation.MISSING_TASK_ID in _violations(excinfo)


@pytest.mark.parametrize(
    "relation,action,task_id",
    [
        (TaskRelation.NEW_TASK, AgentAction.UPDATE_TASK, None),
        (TaskRelation.NEW_TASK, AgentAction.CREATE_TASK, "TASK-001"),
        (TaskRelation.AMBIGUOUS, AgentAction.CREATE_TASK, None),
        (TaskRelation.AMBIGUOUS, AgentAction.ASK_USER, "TASK-001"),
    ],
)
def test_relation_action_contract_is_enforced(relation, action, task_id) -> None:
    hypotheses = _ids([_same(), _draft(relation, action, task_id)])
    with pytest.raises(HypothesisContractError) as excinfo:
        validate_generation(hypotheses, CANDIDATE_IDS)
    assert ContractViolation.INVALID_RELATION_ACTION in _violations(excinfo)


def test_duplicate_hypothesis_is_rejected() -> None:
    hypotheses = _ids([_same(), _same()])
    with pytest.raises(HypothesisContractError) as excinfo:
        validate_generation(hypotheses, CANDIDATE_IDS)
    assert ContractViolation.DUPLICATE_HYPOTHESIS in _violations(excinfo)


def test_single_hypothesis_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValueError):
        HypothesisGeneration(hypotheses=[_same()])


def test_count_outside_the_configured_range_is_rejected() -> None:
    hypotheses = _ids([_same(), _new(), _ambiguous()])
    with pytest.raises(HypothesisContractError) as excinfo:
        validate_generation(hypotheses, CANDIDATE_IDS, max_hypotheses=2)
    assert ContractViolation.TOO_FEW_HYPOTHESES in _violations(excinfo)


def test_more_than_three_hypotheses_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValueError):
        HypothesisGeneration(
            hypotheses=[_same(), _same("TASK-002"), _new(), _ambiguous()]
        )


def test_overlong_evidence_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValueError):
        HypothesisDraft(
            relation=TaskRelation.NEW_TASK,
            action=AgentAction.CREATE_TASK,
            supporting_evidence=["가" * 301],
        )


def _selection(scores: dict[str, float], selected: str) -> HypothesisSelection:
    return HypothesisSelection(
        evaluations=[
            HypothesisEvaluation(
                hypothesis_id=key, support_score=value, evaluation_reason="비교 근거"
            )
            for key, value in scores.items()
        ],
        selected_hypothesis_id=selected,
        confidence=0.9,
        reason="최종 판단 근거",
    )


def test_selection_returns_the_winning_hypothesis() -> None:
    hypotheses = _ids([_same(), _new()])
    winner = validate_selection(_selection({"H1": 0.8, "H2": 0.3}, "H1"), hypotheses)
    assert winner.hypothesis_id == "H1"
    assert winner.relation is TaskRelation.SAME_TASK


def test_missing_evaluation_is_rejected() -> None:
    hypotheses = _ids([_same(), _new(), _ambiguous()])
    with pytest.raises(HypothesisContractError) as excinfo:
        validate_selection(_selection({"H1": 0.8, "H2": 0.3}, "H1"), hypotheses)
    assert ContractViolation.INCOMPLETE_EVALUATION in _violations(excinfo)


def test_unknown_hypothesis_in_evaluation_is_rejected() -> None:
    hypotheses = _ids([_same(), _new()])
    with pytest.raises(HypothesisContractError) as excinfo:
        validate_selection(_selection({"H1": 0.8, "H3": 0.3}, "H1"), hypotheses)
    assert ContractViolation.UNKNOWN_HYPOTHESIS in _violations(excinfo)


def test_selecting_a_lower_scored_hypothesis_is_rejected() -> None:
    hypotheses = _ids([_same(), _new()])
    with pytest.raises(HypothesisContractError) as excinfo:
        validate_selection(_selection({"H1": 0.3, "H2": 0.8}, "H1"), hypotheses)
    assert ContractViolation.SELECTION_SCORE_MISMATCH in _violations(excinfo)


def test_margin_comes_from_the_evaluation_scores() -> None:
    selection = _selection({"H1": 0.82, "H2": 0.31}, "H1")
    assert selection_margin(selection.evaluations) == pytest.approx(0.51)


def test_tied_evaluation_scores_give_a_zero_margin() -> None:
    selection = _selection({"H1": 0.6, "H2": 0.6}, "H1")
    assert selection_margin(selection.evaluations) == 0.0


def test_same_task_rejects_actions_that_contradict_the_relation():
    """Claiming the mail belongs to an existing task while creating a new one.

    SAME_TASK used to be checked only for naming a candidate, so a hypothesis
    could assert both that the mail continues TASK-001 and that a new task
    should be created. The Guard downstream would very likely refuse it, but a
    self-contradictory hypothesis should not reach the evaluation stage.
    """
    for action in (AgentAction.CREATE_TASK, AgentAction.IGNORE, AgentAction.ASK_USER):
        hypotheses = [
            TaskHypothesis(
                hypothesis_id="H1",
                relation=TaskRelation.SAME_TASK,
                selected_task_id="TASK-001",
                action=action,
                supporting_evidence=["같은 업무로 보인다"],
            ),
            TaskHypothesis(
                hypothesis_id="H2",
                relation=TaskRelation.NEW_TASK,
                selected_task_id=None,
                action=AgentAction.CREATE_TASK,
                supporting_evidence=["새 업무로 보인다"],
            ),
        ]
        with pytest.raises(HypothesisContractError) as excinfo:
            validate_generation(hypotheses, {"TASK-001"})
        assert ContractViolation.INVALID_RELATION_ACTION in {
            item.violation for item in excinfo.value.violations
        }, f"SAME_TASK + {action.value} should breach the relation contract"


def test_same_task_admits_the_actions_that_operate_on_a_task():
    for action in (
        AgentAction.UPDATE_TASK,
        AgentAction.LINK_TO_TASK,
        AgentAction.SET_WAITING,
        AgentAction.MARK_COMPLETED,
    ):
        hypotheses = [
            TaskHypothesis(
                hypothesis_id="H1",
                relation=TaskRelation.SAME_TASK,
                selected_task_id="TASK-001",
                action=action,
                supporting_evidence=["같은 업무로 보인다"],
            ),
            TaskHypothesis(
                hypothesis_id="H2",
                relation=TaskRelation.NEW_TASK,
                selected_task_id=None,
                action=AgentAction.CREATE_TASK,
                supporting_evidence=["새 업무로 보인다"],
            ),
        ]
        validate_generation(hypotheses, {"TASK-001"})
