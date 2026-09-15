"""Contract checks for bounded multi-hypothesis deliberation.

No LLM calls happen here. The generation Agent proposes candidate relations, this
module decides whether that response honours the safety contract, and the
evaluation Agent then scores only the candidates that passed.

A contract violation fails the whole response rather than dropping the offending
candidate. Keeping two valid hypotheses and discarding a third that points at a
task the retrieval never returned would hide a plain contract breach and let the
run continue automatically, which is the opposite of failing closed. Low or tied
scores are a different thing entirely: those mean the model looked and could not
tell the candidates apart, which is what the query rewrite path is for.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import (
    AgentAction,
    ContractViolation,
    HypothesisEvaluation,
    HypothesisGeneration,
    HypothesisSelection,
    RejectedHypothesis,
    TaskHypothesis,
    TaskRelation,
)

# NEW_TASK and AMBIGUOUS admit exactly one action and carry no target id.
_RELATION_CONTRACT: dict[TaskRelation, AgentAction] = {
    TaskRelation.NEW_TASK: AgentAction.CREATE_TASK,
    TaskRelation.AMBIGUOUS: AgentAction.ASK_USER,
}

# SAME_TASK names an existing task, so it admits the actions that operate on one.
# Creating a task while claiming the mail belongs to an existing one contradicts
# itself, and ignoring or asking are not statements about that task.
_SAME_TASK_ACTIONS: frozenset[AgentAction] = frozenset(
    {
        AgentAction.UPDATE_TASK,
        AgentAction.LINK_TO_TASK,
        AgentAction.SET_WAITING,
        AgentAction.MARK_COMPLETED,
    }
)


class HypothesisContractError(ValueError):
    """Raised when a model response breaks the deliberation contract."""

    def __init__(self, violations: list[RejectedHypothesis]) -> None:
        self.violations = violations
        detail = ", ".join(
            f"{item.hypothesis_id or '-'}:{item.violation.value}" for item in violations
        )
        super().__init__(f"hypothesis contract violated: {detail}")


def assign_hypothesis_ids(generation: HypothesisGeneration) -> list[TaskHypothesis]:
    """Number the drafts H1..H3 in the order the model returned them.

    Python owns the ids so a duplicated or malformed id from the model can never
    force a schema retry.
    """
    return [
        TaskHypothesis(hypothesis_id=f"H{index}", **draft.model_dump())
        for index, draft in enumerate(generation.hypotheses, start=1)
    ]


def validate_generation(
    hypotheses: list[TaskHypothesis],
    candidate_ids: Iterable[str],
    *,
    min_hypotheses: int = 2,
    max_hypotheses: int = 3,
) -> None:
    """Raise HypothesisContractError unless every hypothesis is admissible."""
    violations: list[RejectedHypothesis] = []

    if not min_hypotheses <= len(hypotheses) <= max_hypotheses:
        violations.append(
            RejectedHypothesis(hypothesis_id=None, violation=ContractViolation.TOO_FEW_HYPOTHESES)
        )

    known_ids = set(candidate_ids)
    seen_shapes: set[tuple[str, str | None, str]] = set()
    seen_ids: set[str] = set()

    for item in hypotheses:
        if item.hypothesis_id in seen_ids:
            violations.append(
                RejectedHypothesis(
                    hypothesis_id=item.hypothesis_id,
                    violation=ContractViolation.DUPLICATE_HYPOTHESIS,
                )
            )
        seen_ids.add(item.hypothesis_id)

        shape = (item.relation.value, item.selected_task_id, item.action.value)
        if shape in seen_shapes:
            violations.append(
                RejectedHypothesis(
                    hypothesis_id=item.hypothesis_id,
                    violation=ContractViolation.DUPLICATE_HYPOTHESIS,
                )
            )
        seen_shapes.add(shape)

        if item.relation is TaskRelation.SAME_TASK:
            if not item.selected_task_id:
                violations.append(
                    RejectedHypothesis(
                        hypothesis_id=item.hypothesis_id,
                        violation=ContractViolation.MISSING_TASK_ID,
                    )
                )
            elif item.selected_task_id not in known_ids:
                violations.append(
                    RejectedHypothesis(
                        hypothesis_id=item.hypothesis_id,
                        violation=ContractViolation.OUTSIDE_CANDIDATE,
                    )
                )
            if item.action not in _SAME_TASK_ACTIONS:
                violations.append(
                    RejectedHypothesis(
                        hypothesis_id=item.hypothesis_id,
                        violation=ContractViolation.INVALID_RELATION_ACTION,
                    )
                )
        else:
            expected_action = _RELATION_CONTRACT[item.relation]
            if item.selected_task_id is not None:
                violations.append(
                    RejectedHypothesis(
                        hypothesis_id=item.hypothesis_id,
                        violation=ContractViolation.INVALID_RELATION_ACTION,
                    )
                )
            elif item.action is not expected_action:
                violations.append(
                    RejectedHypothesis(
                        hypothesis_id=item.hypothesis_id,
                        violation=ContractViolation.INVALID_RELATION_ACTION,
                    )
                )

    if violations:
        raise HypothesisContractError(violations)


def validate_selection(
    selection: HypothesisSelection,
    hypotheses: list[TaskHypothesis],
) -> TaskHypothesis:
    """Raise unless every hypothesis was scored once and the top score was picked."""
    violations: list[RejectedHypothesis] = []
    generated_ids = {item.hypothesis_id for item in hypotheses}
    scored_ids = [item.hypothesis_id for item in selection.evaluations]

    for unknown in sorted(set(scored_ids) - generated_ids):
        violations.append(
            RejectedHypothesis(
                hypothesis_id=unknown, violation=ContractViolation.UNKNOWN_HYPOTHESIS
            )
        )

    for missing in sorted(generated_ids - set(scored_ids)):
        violations.append(
            RejectedHypothesis(
                hypothesis_id=missing, violation=ContractViolation.INCOMPLETE_EVALUATION
            )
        )

    if len(scored_ids) != len(set(scored_ids)):
        violations.append(
            RejectedHypothesis(
                hypothesis_id=None, violation=ContractViolation.INCOMPLETE_EVALUATION
            )
        )

    if selection.selected_hypothesis_id not in generated_ids:
        violations.append(
            RejectedHypothesis(
                hypothesis_id=selection.selected_hypothesis_id,
                violation=ContractViolation.UNKNOWN_HYPOTHESIS,
            )
        )
    elif not violations:
        best = max(selection.evaluations, key=lambda item: item.support_score)
        chosen = next(
            item
            for item in selection.evaluations
            if item.hypothesis_id == selection.selected_hypothesis_id
        )
        if chosen.support_score < best.support_score:
            violations.append(
                RejectedHypothesis(
                    hypothesis_id=selection.selected_hypothesis_id,
                    violation=ContractViolation.SELECTION_SCORE_MISMATCH,
                )
            )

    if violations:
        raise HypothesisContractError(violations)

    return next(
        item
        for item in hypotheses
        if item.hypothesis_id == selection.selected_hypothesis_id
    )


def selection_margin(evaluations: list[HypothesisEvaluation]) -> float:
    """Gap between the best and second-best evaluated score.

    Computed here rather than asked of the model, so the number the guard reacts
    to never comes from the thing being guarded. A tie yields 0.0, which reads as
    "could not tell them apart" and routes to the query rewrite path.
    """
    if len(evaluations) < 2:
        return 0.0
    scores = sorted((item.support_score for item in evaluations), reverse=True)
    return round(scores[0] - scores[1], 6)
