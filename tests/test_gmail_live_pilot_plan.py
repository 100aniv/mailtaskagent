from __future__ import annotations

import json
from pathlib import Path


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

    rendered = json.dumps(cases, ensure_ascii=False).casefold()
    assert "@gmail.com" not in rendered
    assert "api_key=" not in rendered
    assert "authorization:" not in rendered
