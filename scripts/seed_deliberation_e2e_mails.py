"""Authorize the requester test account and send the three E2E seed mails.

The agent owner's mailbox is the one under test, so the seeds have to arrive
from someone else: a mail the owner sends to itself carries Gmail's SENT label
and is read back as OUTBOUND, which is not a new request.

Set both addresses first, then run the two steps; authorising never sends
anything by itself:

    set MTA_E2E_REQUESTER=<sender test account>
    set MTA_E2E_AGENT_OWNER=<mailbox under test>

    .venv\\Scripts\\python.exe -m scripts.seed_deliberation_e2e_mails --authorize
    .venv\\Scripts\\python.exe -m scripts.seed_deliberation_e2e_mails --send

The third mail is the point of the exercise. It names no system, so the agent
has to weigh both existing tasks against a new one instead of matching on a
thread id or a shared word.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from dataclasses import replace
from email.message import EmailMessage
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mailtaskagent.gmail_source import (  # noqa: E402
    build_gmail_service,
    load_gmail_send_source_settings,
)

# Addresses come from the operator's environment and are never committed.
# REQUESTER is the test account the seeds are sent from; AGENT_OWNER is the
# mailbox under test.
REQUESTER = os.environ.get("MTA_E2E_REQUESTER", "")
AGENT_OWNER = os.environ.get("MTA_E2E_AGENT_OWNER", "")
TOKEN_PATH = PROJECT_ROOT / ".secrets" / "gmail_requester_send_token.json"
SUBJECT_PREFIX = "[MTA-DLB-0915]"

SEED_MAILS = [
    (
        f"{SUBJECT_PREFIX} 접근통제 서버 점검 일정 회신 요청",
        "접근통제 서버 2대의 점검 가능 일정을 2026년 9월 17일까지 회신해 주세요.",
    ),
    (
        f"{SUBJECT_PREFIX} 인증 서버 점검 일정 회신 요청",
        "인증 서버 2대의 점검 가능 일정을 2026년 9월 17일까지 회신해 주세요.",
    ),
    (
        f"{SUBJECT_PREFIX} 지난 점검 건 일정 확인 부탁드립니다",
        "앞서 요청드린 점검 건의 담당자 배정이 끝났습니다. 진행 일정을 확인해 회신 부탁드립니다.",
    ),
]


def _requester_settings():
    return replace(load_gmail_send_source_settings(), token_path=TOKEN_PATH)


def _service(*, interactive: bool):
    return build_gmail_service(
        _requester_settings(),
        allow_interactive_auth=interactive,
        include_send_scope=True,
    )


def _assert_requester(service) -> str:
    address = service.users().getProfile(userId="me").execute()["emailAddress"]
    if address.lower() != REQUESTER.lower():
        TOKEN_PATH.unlink(missing_ok=True)
        raise SystemExit(
            f"Authorized as {address}, but the seeds must come from {REQUESTER}. "
            "The saved token was removed; run --authorize again and pick that account."
        )
    return address


def authorize() -> int:
    print(f"Opening the Google consent screen. Sign in as {REQUESTER}.")
    print("Only the Gmail send scope is requested, and the token is written to")
    print(f"  {TOKEN_PATH}")
    service = _service(interactive=True)
    address = _assert_requester(service)
    print(f"Authorized as {address}. Nothing has been sent.")
    return 0


def send(output: Path) -> int:
    service = _service(interactive=False)
    address = _assert_requester(service)

    sent = []
    for subject, body in SEED_MAILS:
        message = EmailMessage()
        message["To"] = AGENT_OWNER
        message["From"] = address
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        sent.append(
            {
                "subject": subject,
                "body": body,
                "gmail_message_id": result["id"],
                "thread_id": result["threadId"],
            }
        )
        print(f"sent {result['id']}  {subject}")

    thread_ids = {item["thread_id"] for item in sent}
    report = {
        "evidence_type": "deliberation_e2e_seed_mails",
        "from": "requester-test-account",
        "to": "agent-owner-test-account",
        "subject_prefix": SUBJECT_PREFIX,
        "mails": sent,
        "distinct_threads": len(thread_ids),
        "note": (
            "세 통 모두 새 메일이라 Thread가 서로 다르다. 세 번째 메일은 대상 시스템을 "
            "적지 않아 THREAD_EXACT로 확정할 수 없고 숙고 경로로 들어간다."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(sent)} mails sent from {address} to {AGENT_OWNER}")
    print(f"distinct threads: {len(thread_ids)} (3 expected)")
    print("wrote", output)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--authorize", action="store_true")
    group.add_argument("--send", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "evidence" / "gmail_deliberation_e2e_seeds_2026-09-15.json",
    )
    args = parser.parse_args()
    missing = [
        name
        for name, value in (
            ("MTA_E2E_REQUESTER", REQUESTER),
            ("MTA_E2E_AGENT_OWNER", AGENT_OWNER),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"Set these environment variables first: {', '.join(missing)}")
    return authorize() if args.authorize else send(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
