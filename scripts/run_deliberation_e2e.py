"""Drive the bounded-deliberation Gmail E2E and stop before anything is sent.

Fetches the restricted demo label, lets the workflow process whatever is new,
then reports what the two deliberation stages produced. It never sends a mail:
the approved-send step stays with the user, who confirms the recipient, the
thread and the body first.

    .venv\\Scripts\\python.exe -m scripts.run_deliberation_e2e --prefix "[MTA-DLB-0915]"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mailtaskagent.config import load_settings  # noqa: E402
from mailtaskagent.gmail_source import (  # noqa: E402
    GmailReadOnlySource,
    build_gmail_service,
    load_gmail_source_settings,
)
from mailtaskagent.llm_client import build_analyzer  # noqa: E402
from mailtaskagent.operations import MailSyncService  # noqa: E402
from mailtaskagent.storage import SQLiteStorage  # noqa: E402

DELIBERATION_STEPS = (
    "M-03 HYPOTHESIS_GENERATION",
    "M-03 HYPOTHESIS_VALIDATION",
    "M-03 HYPOTHESIS_EVALUATION",
    "M-03 DELIBERATION_DECISION",
    "M-03 HYPOTHESIS_REGENERATION",
    "M-03 HYPOTHESIS_REVALIDATION",
    "M-03 HYPOTHESIS_REEVALUATION",
    "M-03 DELIBERATION_REDECISION",
)


class _StorageBackedGmailSource:
    """Same construction the operations CLI uses, so the fetch matches production."""

    def __init__(self, storage) -> None:
        self.storage = storage

    def load(self):
        gmail_settings = load_gmail_source_settings()
        service = build_gmail_service(gmail_settings, allow_interactive_auth=False)
        return GmailReadOnlySource(
            service,
            gmail_settings,
            tracked_conversation_ids=[
                task["conversation_id"] for task in self.storage.list_tasks()
            ],
        ).load()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, help="subject prefix of this run")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    settings = load_settings()
    if not settings.agent_deliberation_enabled:
        raise SystemExit("AGENT_DELIBERATION_ENABLED must be on for this run")
    storage = SQLiteStorage(settings.database_path)

    before = {
        "tasks": len(storage.list_tasks()),
        "mails": len(storage.list_mails()),
        "events": len(storage.list_events()),
    }

    report = MailSyncService(
        settings=settings,
        storage=storage,
        analyzer=build_analyzer(settings),
        source=_StorageBackedGmailSource(storage),
        source_name="GMAIL",
    ).run_once()

    mails = [m for m in storage.list_mails() if args.prefix in (m.get("subject") or "")]
    mail_ids = {m["mail_id"] for m in mails}
    events = [e for e in storage.list_events() if e["mail_id"] in mail_ids]
    by_step: dict[str, list[dict]] = {}
    for event in events:
        by_step.setdefault(event["step"], []).append(event)

    def details(step: str) -> list[dict]:
        return [json.loads(e["details_json"] or "{}") for e in by_step.get(step, [])]

    result = {
        "prefix": args.prefix,
        "sync": {
            "status": report.status,
            "fetched": report.fetched_count,
            "new": report.succeeded_count,
            "duplicates": report.duplicate_count,
            "failed": report.failed_count,
            "error_type": report.error_type,
        },
        "before": before,
        "after": {
            "tasks": len(storage.list_tasks()),
            "mails": len(storage.list_mails()),
            "events": len(storage.list_events()),
        },
        "mails_in_run": [
            {"mail_id": m["mail_id"], "direction": m["direction"], "subject": m["subject"]}
            for m in sorted(mails, key=lambda x: x["occurred_at"])
        ],
        "deliberation_steps_seen": {
            step: len(by_step.get(step, [])) for step in DELIBERATION_STEPS
        },
        "generation": details("M-03 HYPOTHESIS_GENERATION"),
        "evaluation": details("M-03 HYPOTHESIS_EVALUATION"),
        "decision": details("M-03 DELIBERATION_DECISION"),
        "regeneration": details("M-03 HYPOTHESIS_REGENERATION"),
        "reevaluation": details("M-03 HYPOTHESIS_REEVALUATION"),
        "redecision": details("M-03 DELIBERATION_REDECISION"),
        "guard": details("M-03 PYTHON_GUARD"),
        "final_actions": details("M-03 ACTION_DECISION"),
        "pending_reviews": [
            {"mail_id": r["mail_id"], "reason": r.get("reason")}
            for r in storage.list_pending_reviews()
        ],
        "note": "No mail was sent by this script. The approved send stays a user step.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: result[k] for k in ("sync", "before", "after", "deliberation_steps_seen")},
                     ensure_ascii=False))
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
