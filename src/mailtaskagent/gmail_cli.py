from __future__ import annotations

import argparse

from mailtaskagent.config import load_settings
from mailtaskagent.gmail_source import (
    GmailReadOnlySource,
    build_gmail_service,
    load_gmail_send_source_settings,
    load_gmail_source_settings,
)
from mailtaskagent.mail_filters import build_operational_analyzer
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read synthetic test mail from a restricted Gmail label."
    )
    parser.add_argument(
        "--process",
        action="store_true",
        help="Run fetched test mail through the existing Agent Core and SQLite.",
    )
    parser.add_argument(
        "--reauthorize",
        action="store_true",
        help="Open an explicit Gmail read-only consent flow and replace the token only after success.",
    )
    parser.add_argument(
        "--authorize-send",
        action="store_true",
        help="Explicitly replace the token after consenting to Gmail read and send scopes.",
    )
    args = parser.parse_args()

    gmail_settings = load_gmail_source_settings()
    authorization_settings = (
        load_gmail_send_source_settings() if args.authorize_send else gmail_settings
    )
    source = GmailReadOnlySource(
        build_gmail_service(
            authorization_settings,
            force_reauthorization=args.reauthorize or args.authorize_send,
            include_send_scope=args.authorize_send,
        ),
        gmail_settings,
    )
    mails = source.load()
    access_label = "read + approved send" if args.authorize_send else "read-only"
    print(
        f"Gmail {access_label} source: {len(mails)} mail(s), "
        f"query={gmail_settings.query!r}"
    )
    if not args.process:
        for mail in mails:
            print(
                f"- {mail.mail_id} | {mail.direction.value} | "
                f"{mail.occurred_at.isoformat()} | {mail.subject}"
            )
        print("Preview only. Add --process to run the Agent Core.")
        return 0

    settings = load_settings()
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(
        settings,
        storage,
        build_operational_analyzer(settings, storage),
    )
    failed = 0
    for mail in mails:
        try:
            result = workflow.process(mail)
            print(
                f"- {mail.mail_id}: {result.proposal.action.value} "
                f"task={result.proposal.target_task_id or '-'}"
            )
        except Exception as error:
            failed += 1
            print(f"- {mail.mail_id}: FAILED ({type(error).__name__})")
    print(f"Processed={len(mails) - failed}, Failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
