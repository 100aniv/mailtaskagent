from __future__ import annotations

import json
from pathlib import Path

from mailtaskagent.gmail_pilot import evaluate_gmail_pilot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = PROJECT_ROOT / "data" / "gmail_live_pilot_cases.json"


def test_gmail_live_pilot_plan_covers_twenty_mails_and_all_actions() -> None:
    cases = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    assert len(cases) == 20
    assert [case["sequence"] for case in cases] == list(range(1, 21))
    assert len({case["case_id"] for case in cases}) == 20
    assert {case["direction"] for case in cases} == {"INBOUND", "OUTBOUND"}
    assert {case["expected_action"] for case in cases} == {
        "CREATE_TASK",
        "UPDATE_TASK",
        "LINK_TO_TASK",
        "SET_WAITING",
        "MARK_COMPLETED",
        "ASK_USER",
        "IGNORE",
    }
    assert sum(case["review_required"] for case in cases) >= 5
    assert all(case["case_id"] in case["body"] for case in cases)

    rendered = json.dumps(cases, ensure_ascii=False).casefold()
    assert "@gmail.com" not in rendered
    assert "api_key=" not in rendered
    assert "authorization:" not in rendered


def test_gmail_live_pilot_report_checks_direction_thread_action_and_review() -> None:
    cases = json.loads(PLAN_PATH.read_text(encoding="utf-8"))[:2]
    mails = [
        {
            "mail_id": "MSG-1",
            "conversation_id": "THREAD-1",
            "direction": "INBOUND",
            "subject": cases[0]["subject"],
            "body": cases[0]["body"],
        },
        {
            "mail_id": "MSG-2",
            "conversation_id": "THREAD-1",
            "direction": "INBOUND",
            "subject": cases[1]["subject"],
            "body": cases[1]["body"],
        },
    ]
    results = [
        {
            "mail_id": "MSG-1",
            "result": {
                "proposal": {
                    "action": "CREATE_TASK",
                    "needs_user_confirmation": False,
                }
            },
        },
        {
            "mail_id": "MSG-2",
            "result": {
                "proposal": {
                    "action": "UPDATE_TASK",
                    "needs_user_confirmation": False,
                }
            },
        },
    ]

    report = evaluate_gmail_pilot(cases, mails, results)

    assert report["status"] == "PASSED"
    assert report["passed_cases"] == 2
    assert report["failed_cases"] == 0
    assert report["pending_cases"] == 0


def test_gmail_live_pilot_report_never_passes_missing_or_wrong_direction() -> None:
    cases = json.loads(PLAN_PATH.read_text(encoding="utf-8"))[:2]
    mails = [
        {
            "mail_id": "MSG-1",
            "conversation_id": "THREAD-1",
            "direction": "OUTBOUND",
            "subject": cases[0]["subject"],
            "body": cases[0]["body"],
        }
    ]
    results = [
        {
            "mail_id": "MSG-1",
            "result": {
                "proposal": {
                    "action": "CREATE_TASK",
                    "needs_user_confirmation": False,
                }
            },
        }
    ]

    report = evaluate_gmail_pilot(cases, mails, results)

    assert report["status"] == "INCOMPLETE"
    assert report["failed_cases"] == 1
    assert report["pending_cases"] == 1


def test_gmail_live_pilot_report_fails_duplicate_marker_and_crossed_threads() -> None:
    cases = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    selected_cases = [cases[0], cases[3]]
    mails = [
        {
            "mail_id": "MSG-1",
            "conversation_id": "CROSSED-THREAD",
            "direction": "INBOUND",
            "subject": selected_cases[0]["subject"],
            "body": selected_cases[0]["body"],
        },
        {
            "mail_id": "MSG-1-DUPLICATE",
            "conversation_id": "CROSSED-THREAD",
            "direction": "INBOUND",
            "subject": selected_cases[0]["subject"],
            "body": selected_cases[0]["body"],
        },
        {
            "mail_id": "MSG-4",
            "conversation_id": "CROSSED-THREAD",
            "direction": "INBOUND",
            "subject": selected_cases[1]["subject"],
            "body": selected_cases[1]["body"],
        },
    ]
    results = [
        {
            "mail_id": "MSG-1",
            "result": {
                "proposal": {
                    "action": "CREATE_TASK",
                    "needs_user_confirmation": False,
                }
            },
        },
        {
            "mail_id": "MSG-4",
            "result": {
                "proposal": {
                    "action": "CREATE_TASK",
                    "needs_user_confirmation": False,
                }
            },
        },
    ]

    report = evaluate_gmail_pilot(selected_cases, mails, results)

    assert report["status"] == "INCOMPLETE"
    assert report["failed_cases"] == 2
    assert all(row["status"] == "FAILED" for row in report["cases"])
