from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from mailtaskagent.config import PROJECT_ROOT, Settings
from mailtaskagent.llm_client import MailAnalyzer
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow, load_mails


def load_scenario_expectations(
    path: Path = PROJECT_ROOT / "data" / "scenario_expectations.json",
) -> list[dict]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def load_saved_evaluation_report(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def load_kpi_ground_truth(
    path: Path = PROJECT_ROOT / "data" / "kpi_ground_truth.json",
) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _summary_matches(actual: str | None, term_groups: list[list[str]]) -> bool:
    if not actual:
        return False
    normalized = actual.casefold()
    return all(any(term.casefold() in normalized for term in group) for group in term_groups)


def _calculate_detailed_kpis(
    ground_truth: dict,
    analyses_by_mail: dict[str, dict],
    actual_task_links: dict[tuple[str, int], str | None],
) -> dict:
    mail_rows: list[dict] = []
    classification_correct = 0
    intent_correct = 0
    field_correct = 0
    field_total = 0

    for expected in ground_truth["mails"]:
        mail_id = expected["mail_id"]
        actual = analyses_by_mail.get(mail_id)
        expected_task = expected["is_task_request"]
        actual_task = actual.get("is_task_request") if actual else None
        classification_passed = actual_task == expected_task
        classification_correct += classification_passed

        expected_intent = expected["intent"]
        actual_intent = actual.get("intent") if actual else None
        intent_passed = actual_intent == expected_intent
        intent_correct += intent_passed

        summary_passed: bool | None = None
        due_date_passed: bool | None = None
        if expected["evaluate_fields"]:
            summary_passed = _summary_matches(
                actual.get("request_summary") if actual else None,
                expected["request_summary_term_groups"],
            )
            actual_due_date = actual.get("due_date") if actual else None
            due_date_passed = actual_due_date == expected["due_date"]
            field_correct += int(summary_passed) + int(due_date_passed)
            field_total += 2

        mail_rows.append(
            {
                "mail_id": mail_id,
                "expected_is_task_request": expected_task,
                "actual_is_task_request": actual_task,
                "classification_passed": classification_passed,
                "expected_intent": expected_intent,
                "actual_intent": actual_intent,
                "intent_passed": intent_passed,
                "expected_summary_terms": " AND ".join(
                    "/".join(group) for group in expected["request_summary_term_groups"]
                )
                or "-",
                "actual_request_summary": actual.get("request_summary") if actual else None,
                "request_summary_passed": summary_passed,
                "expected_due_date": expected["due_date"],
                "actual_due_date": actual.get("due_date") if actual else None,
                "due_date_passed": due_date_passed,
            }
        )

    task_link_rows: list[dict] = []
    for expected in ground_truth["task_links"]:
        key = (expected["case_id"], expected["step_index"])
        actual_task_id = actual_task_links.get(key)
        task_link_rows.append(
            {
                **expected,
                "actual_task_id": actual_task_id,
                "passed": actual_task_id == expected["expected_task_id"],
            }
        )

    classification_total = len(mail_rows)
    intent_total = len(mail_rows)
    task_link_correct = sum(row["passed"] for row in task_link_rows)
    task_link_total = len(task_link_rows)
    return {
        "mail_classification_accuracy": (
            classification_correct / classification_total if classification_total else 0
        ),
        "mail_classification_correct": classification_correct,
        "mail_classification_total": classification_total,
        "intent_accuracy": intent_correct / intent_total if intent_total else 0,
        "intent_correct": intent_correct,
        "intent_total": intent_total,
        "field_extraction_accuracy": field_correct / field_total if field_total else 0,
        "field_extraction_correct": field_correct,
        "field_extraction_total": field_total,
        "task_link_accuracy": (
            task_link_correct / task_link_total if task_link_total else 0
        ),
        "task_link_correct": task_link_correct,
        "task_link_total": task_link_total,
        "mail_kpi_rows": mail_rows,
        "task_link_rows": task_link_rows,
    }


def _check_case(case: dict, results: list, storage: SQLiteStorage) -> list[str]:
    failures: list[str] = []
    actual_actions = [result.proposal.action.value for result in results]
    if actual_actions != case["expected_actions"]:
        failures.append("Action 순서 불일치")

    final_result = results[-1]
    if case.get("review_required") and not final_result.proposal.needs_user_confirmation:
        failures.append("사용자 확인 누락")
    if "expected_candidate_count" in case and (
        len(final_result.candidate_tasks) != case["expected_candidate_count"]
    ):
        failures.append("후보 수 불일치")

    tasks = storage.list_tasks()
    histories = storage.list_histories()
    if "expected_task_count" in case and len(tasks) != case["expected_task_count"]:
        failures.append("Task 수 불일치")
    if "expected_history_count" in case and (
        len(histories) != case["expected_history_count"]
    ):
        failures.append("History 수 불일치")
    if case.get("second_result_duplicate") and not final_result.duplicate:
        failures.append("중복 처리 차단 실패")

    if tasks:
        expected_status = case.get("expected_final_status")
        expected_status = case.get("expected_final_status_before_review", expected_status)
        if expected_status and tasks[0]["status"] != expected_status:
            failures.append("최종 상태 불일치")
        if "expected_due_date" in case and tasks[0]["due_date"] != case["expected_due_date"]:
            failures.append("기한 불일치")
        if "expected_due_date_before_review" in case and (
            tasks[0]["due_date"] != case["expected_due_date_before_review"]
        ):
            failures.append("승인 전 기한 불일치")

    if "expected_status_sequence" in case:
        actual_statuses = [result.task["status"] if result.task else None for result in results]
        if actual_statuses != case["expected_status_sequence"]:
            failures.append("상태 전이 순서 불일치")
    return failures


def run_scenario_evaluation(
    settings: Settings,
    analyzer: MailAnalyzer,
    *,
    mode: str,
) -> dict:
    """Run every scenario in an isolated DB and compare it with checked-in expectations."""
    expectations = load_scenario_expectations()
    ground_truth = load_kpi_ground_truth()
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    rows: list[dict] = []
    total_action_steps = 0
    correct_action_steps = 0
    analyses_by_mail: dict[str, dict] = {}
    actual_task_links: dict[tuple[str, int], str | None] = {}
    started = perf_counter()
    temp_root = PROJECT_ROOT / "tmp"
    temp_root.mkdir(exist_ok=True)

    with TemporaryDirectory(prefix="evaluation-", dir=temp_root) as temp_dir:
        for index, case in enumerate(expectations, start=1):
            case_started = perf_counter()
            database_path = Path(temp_dir) / f"case-{index:02d}.db"
            storage = SQLiteStorage(database_path)
            case_settings = replace(settings, database_path=database_path)
            workflow = MailTaskWorkflow(case_settings, storage, analyzer)
            results = []
            error = None
            try:
                results = [workflow.process(mails[mail_id]) for mail_id in case["mail_ids"]]
                failures = _check_case(case, results, storage)
                for step_index, result in enumerate(results):
                    analyses_by_mail.setdefault(
                        result.mail.mail_id,
                        result.analysis.model_dump(mode="json"),
                    )
                    actual_task_links[(case["case_id"], step_index)] = (
                        result.proposal.target_task_id
                    )
            except Exception as exc:  # one failed case must not hide the remaining evidence
                failures = ["실행 오류"]
                error = f"{type(exc).__name__}: {exc}"

            expected_actions = case["expected_actions"]
            actual_actions = [result.proposal.action.value for result in results]
            total_action_steps += len(expected_actions)
            correct_action_steps += sum(
                expected == actual
                for expected, actual in zip(expected_actions, actual_actions, strict=False)
            )
            final_result = results[-1] if results else None
            rows.append(
                {
                    "case_id": case["case_id"],
                    "title": case["title"],
                    "expected_actions": " → ".join(expected_actions),
                    "actual_actions": " → ".join(actual_actions) if actual_actions else "-",
                    "passed": not failures,
                    "review_expected": bool(case.get("review_required")),
                    "review_actual": bool(
                        final_result and final_result.proposal.needs_user_confirmation
                    ),
                    "failure_reason": ", ".join(failures) if failures else "-",
                    "error": error or "-",
                    "duration_ms": round((perf_counter() - case_started) * 1000),
                }
            )

    passed_count = sum(row["passed"] for row in rows)
    review_count = sum(row["review_actual"] for row in rows)
    case_count = len(rows)
    detailed_kpis = _calculate_detailed_kpis(
        ground_truth,
        analyses_by_mail,
        actual_task_links,
    )
    return {
        "mode": mode,
        "case_count": case_count,
        "passed_count": passed_count,
        "scenario_pass_rate": passed_count / case_count if case_count else 0,
        "action_step_accuracy": (
            correct_action_steps / total_action_steps if total_action_steps else 0
        ),
        "review_rate": review_count / case_count if case_count else 0,
        "automatic_rate": (case_count - review_count) / case_count if case_count else 0,
        "total_action_steps": total_action_steps,
        "duration_ms": round((perf_counter() - started) * 1000),
        "rows": rows,
        **detailed_kpis,
    }
