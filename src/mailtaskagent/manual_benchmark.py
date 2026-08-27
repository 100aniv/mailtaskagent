from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from mailtaskagent.config import PROJECT_ROOT
from mailtaskagent.evaluation import load_scenario_expectations
from mailtaskagent.workflow import load_mails


BENCHMARK_CASE_IDS = ("BC-01", "BC-04", "BC-11")


def load_manual_benchmark_cases() -> list[dict]:
    """Return the three core scenarios without exposing their expected answers."""
    expectations = {
        case["case_id"]: case for case in load_scenario_expectations()
    }
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    cases: list[dict] = []
    for case_id in BENCHMARK_CASE_IDS:
        case = expectations[case_id]
        steps = []
        for step_index, mail_id in enumerate(case["mail_ids"]):
            mail = mails[mail_id]
            steps.append(
                {
                    "step_index": step_index,
                    "mail_id": mail_id,
                    "direction": mail.direction.value,
                    "occurred_at": mail.occurred_at.isoformat(),
                    "subject": mail.subject,
                    "body": mail.body,
                }
            )
        cases.append(
            {
                "case_id": case_id,
                "title": case["title"],
                "steps": steps,
            }
        )
    return cases


def calculate_manual_benchmark_result(
    answers: dict[str, str],
    *,
    manual_duration_ms: int,
    agent_report: dict,
    started_at: str,
    completed_at: str,
) -> dict:
    """Compare a user's manual decisions with the same Live scenario subset."""
    if manual_duration_ms <= 0:
        raise ValueError("manual_duration_ms must be positive")

    expectations = {
        case["case_id"]: case for case in load_scenario_expectations()
    }
    rows: list[dict] = []
    for case_id in BENCHMARK_CASE_IDS:
        case = expectations[case_id]
        for step_index, (mail_id, expected_action) in enumerate(
            zip(case["mail_ids"], case["expected_actions"], strict=True)
        ):
            key = f"{case_id}:{step_index}"
            actual_action = answers.get(key)
            rows.append(
                {
                    "case_id": case_id,
                    "step_index": step_index,
                    "mail_id": mail_id,
                    "expected_action": expected_action,
                    "actual_action": actual_action,
                    "passed": actual_action == expected_action,
                }
            )

    live_rows = {row["case_id"]: row for row in agent_report.get("rows", [])}
    missing_live_cases = [
        case_id for case_id in BENCHMARK_CASE_IDS if case_id not in live_rows
    ]
    if missing_live_cases:
        raise ValueError(
            "Live evaluation report is missing benchmark cases: "
            + ", ".join(missing_live_cases)
        )

    action_total = len(rows)
    action_correct = sum(row["passed"] for row in rows)
    manual_action_accuracy = action_correct / action_total if action_total else 0
    agent_duration_ms = sum(
        int(live_rows[case_id]["duration_ms"]) for case_id in BENCHMARK_CASE_IDS
    )
    kpi_eligible = manual_action_accuracy == 1
    time_reduction_rate = None
    if kpi_eligible:
        time_reduction_rate = (manual_duration_ms - agent_duration_ms) / manual_duration_ms

    return {
        "benchmark_version": 1,
        "measurement_scope": "SC-001·SC-002·SC-003 representative cases",
        "benchmark_case_ids": list(BENCHMARK_CASE_IDS),
        "started_at": started_at,
        "completed_at": completed_at,
        "manual_duration_ms": manual_duration_ms,
        "agent_duration_ms": agent_duration_ms,
        "manual_action_correct": action_correct,
        "manual_action_total": action_total,
        "manual_action_accuracy": manual_action_accuracy,
        "kpi_eligible": kpi_eligible,
        "time_reduction_rate": time_reduction_rate,
        "target_rate": 0.3,
        "target_met": bool(
            time_reduction_rate is not None and time_reduction_rate >= 0.3
        ),
        "agent_evidence_generated_at": agent_report.get("generated_at"),
        "agent_model": agent_report.get("model"),
        "rows": rows,
    }


def save_manual_benchmark_evidence(
    result: dict,
    *,
    evidence_dir: Path = PROJECT_ROOT / "evidence",
) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
    path = evidence_dir / f"manual_time_benchmark_{timestamp}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
