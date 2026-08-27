from pathlib import Path

import pytest

from mailtaskagent.manual_benchmark import (
    BENCHMARK_CASE_IDS,
    calculate_manual_benchmark_result,
    load_manual_benchmark_cases,
    save_manual_benchmark_evidence,
)


def _agent_report() -> dict:
    return {
        "mode": "LIVE",
        "generated_at": "2026-08-27T15:17:37+09:00",
        "model": "gpt-4.1-mini",
        "rows": [
            {"case_id": "BC-01", "duration_ms": 1_000},
            {"case_id": "BC-04", "duration_ms": 2_000},
            {"case_id": "BC-11", "duration_ms": 3_000},
        ],
    }


def _correct_answers() -> dict[str, str]:
    return {
        "BC-01:0": "CREATE_TASK",
        "BC-04:0": "CREATE_TASK",
        "BC-04:1": "UPDATE_TASK",
        "BC-11:0": "CREATE_TASK",
        "BC-11:1": "CREATE_TASK",
        "BC-11:2": "ASK_USER",
    }


def test_manual_benchmark_uses_three_core_scenarios_without_answers() -> None:
    cases = load_manual_benchmark_cases()

    assert tuple(case["case_id"] for case in cases) == BENCHMARK_CASE_IDS
    assert sum(len(case["steps"]) for case in cases) == 6
    assert all("expected_action" not in step for case in cases for step in case["steps"])


def test_manual_benchmark_calculates_same_case_time_reduction() -> None:
    result = calculate_manual_benchmark_result(
        _correct_answers(),
        manual_duration_ms=10_000,
        agent_report=_agent_report(),
        started_at="2026-08-27T16:00:00+09:00",
        completed_at="2026-08-27T16:00:10+09:00",
    )

    assert result["manual_action_correct"] == result["manual_action_total"] == 6
    assert result["kpi_eligible"] is True
    assert result["agent_duration_ms"] == 6_000
    assert result["time_reduction_rate"] == pytest.approx(0.4)
    assert result["target_met"] is True


def test_inaccurate_manual_run_is_excluded_from_time_kpi() -> None:
    answers = _correct_answers()
    answers["BC-11:2"] = "CREATE_TASK"

    result = calculate_manual_benchmark_result(
        answers,
        manual_duration_ms=10_000,
        agent_report=_agent_report(),
        started_at="2026-08-27T16:00:00+09:00",
        completed_at="2026-08-27T16:00:10+09:00",
    )

    assert result["manual_action_accuracy"] == pytest.approx(5 / 6)
    assert result["kpi_eligible"] is False
    assert result["time_reduction_rate"] is None
    assert result["target_met"] is False


def test_manual_benchmark_evidence_is_saved_as_json(tmp_path: Path) -> None:
    result = calculate_manual_benchmark_result(
        _correct_answers(),
        manual_duration_ms=10_000,
        agent_report=_agent_report(),
        started_at="2026-08-27T16:00:00+09:00",
        completed_at="2026-08-27T16:00:10+09:00",
    )

    path = save_manual_benchmark_evidence(result, evidence_dir=tmp_path)

    assert path.parent == tmp_path
    assert path.name.startswith("manual_time_benchmark_")
    assert '"manual_action_total": 6' in path.read_text(encoding="utf-8")
