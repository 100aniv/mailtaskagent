from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mailtaskagent.config import PROJECT_ROOT


DEFAULT_PILOT_PLAN_PATH = PROJECT_ROOT / "data" / "gmail_live_pilot_cases.json"
CASE_ID_PATTERN = re.compile(r"\bGL-\d{3}\b", re.IGNORECASE)


def load_gmail_pilot_cases(path: Path = DEFAULT_PILOT_PLAN_PATH) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    case_ids = [str(case["case_id"]).upper() for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Gmail pilot case IDs must be unique")
    return cases


def _case_id_from_mail(mail: dict[str, Any]) -> str | None:
    searchable = f"{mail.get('subject', '')}\n{mail.get('body', '')}"
    match = CASE_ID_PATTERN.search(searchable)
    return match.group(0).upper() if match else None


def evaluate_gmail_pilot(
    cases: list[dict[str, Any]],
    mails: list[dict[str, Any]],
    processing_results: list[dict[str, Any]],
) -> dict[str, Any]:
    mails_by_case: dict[str, list[dict[str, Any]]] = {}
    for mail in mails:
        case_id = _case_id_from_mail(mail)
        if case_id:
            mails_by_case.setdefault(case_id, []).append(mail)

    results_by_mail_id = {row["mail_id"]: row for row in processing_results}
    sequence_to_case_id = {int(case["sequence"]): case["case_id"] for case in cases}
    cases_by_id = {case["case_id"]: case for case in cases}
    thread_ids_by_key: dict[str, set[str]] = {}
    thread_keys_by_id: dict[str, set[str]] = {}
    for case_id, matched_mails in mails_by_case.items():
        case = cases_by_id.get(case_id)
        if case is None:
            continue
        for matched_mail in matched_mails:
            thread_id = str(matched_mail.get("conversation_id", ""))
            thread_key = str(case["thread_key"])
            thread_ids_by_key.setdefault(thread_key, set()).add(thread_id)
            thread_keys_by_id.setdefault(thread_id, set()).add(thread_key)
    case_rows: list[dict[str, Any]] = []

    for case in cases:
        case_id = case["case_id"]
        matched_mails = mails_by_case.get(case_id, [])
        mail = matched_mails[0] if len(matched_mails) == 1 else None
        result_row = results_by_mail_id.get(mail["mail_id"]) if mail else None
        result = result_row.get("result", {}) if result_row else {}
        proposal = result.get("proposal", {})

        duplicate_marker_ok = len(matched_mails) == 1
        observed = mail is not None
        processed = result_row is not None
        direction_ok = observed and mail.get("direction") == case["direction"]
        action_ok = processed and proposal.get("action") == case["expected_action"]
        review_ok = processed and bool(proposal.get("needs_user_confirmation")) == bool(
            case["review_required"]
        )

        reply_to_sequence = case.get("reply_to_sequence")
        if not observed:
            thread_ok = False
        elif reply_to_sequence is None:
            thread_ok = True
        else:
            parent_case_id = sequence_to_case_id[int(reply_to_sequence)]
            parent_mails = mails_by_case.get(parent_case_id, [])
            thread_ok = (
                len(parent_mails) == 1
                and mail.get("conversation_id") == parent_mails[0].get("conversation_id")
            )

        if observed:
            thread_id = str(mail.get("conversation_id", ""))
            thread_key = str(case["thread_key"])
            thread_ok = (
                thread_ok
                and len(thread_ids_by_key.get(thread_key, set())) == 1
                and len(thread_keys_by_id.get(thread_id, set())) == 1
            )

        passed = all(
            (observed, processed, direction_ok, action_ok, review_ok, thread_ok, duplicate_marker_ok)
        )
        if passed:
            status = "PASSED"
        elif len(matched_mails) > 1:
            status = "FAILED"
        elif not observed or not processed:
            status = "PENDING"
        else:
            status = "FAILED"

        case_rows.append(
            {
                "case_id": case_id,
                "status": status,
                "expected_direction": case["direction"],
                "actual_direction": mail.get("direction") if mail else None,
                "expected_action": case["expected_action"],
                "actual_action": proposal.get("action") if processed else None,
                "expected_review": bool(case["review_required"]),
                "actual_review": (
                    bool(proposal.get("needs_user_confirmation")) if processed else None
                ),
                "checks": {
                    "single_mail_found": duplicate_marker_ok,
                    "processed": processed,
                    "direction": direction_ok,
                    "thread": thread_ok,
                    "action": action_ok,
                    "review": review_ok,
                },
            }
        )

    status_counts = {
        status: sum(row["status"] == status for row in case_rows)
        for status in ("PASSED", "FAILED", "PENDING")
    }
    return {
        "status": "PASSED" if status_counts["PASSED"] == len(cases) else "INCOMPLETE",
        "total_cases": len(cases),
        "observed_cases": sum(bool(mails_by_case.get(case["case_id"])) for case in cases),
        "processed_cases": sum(row["checks"]["processed"] for row in case_rows),
        "passed_cases": status_counts["PASSED"],
        "failed_cases": status_counts["FAILED"],
        "pending_cases": status_counts["PENDING"],
        "cases": case_rows,
    }
