from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mailtaskagent.config import PROJECT_ROOT, load_settings
from mailtaskagent.evaluation import load_kpi_ground_truth, run_scenario_evaluation
from mailtaskagent.llm_client import MockMailAnalyzer, build_analyzer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MailTaskAgent KPI evaluation runner")
    parser.add_argument("--mode", choices=("MOCK", "LIVE"), required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    if args.mode == "LIVE":
        if settings.use_mock:
            raise SystemExit(
                "LIVE mode requires COMPANY_LLM_API_KEY and COMPANY_LLM_USE_MOCK=false"
            )
        analyzer = build_analyzer(settings)
        model = settings.model
    else:
        analyzer = MockMailAnalyzer()
        model = "deterministic-mock"

    report = run_scenario_evaluation(settings, analyzer, mode=args.mode)
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    report["generated_at"] = now.isoformat(timespec="seconds")
    report["model"] = model
    report["ground_truth_version"] = load_kpi_ground_truth()["version"]

    output_path = args.output
    if output_path is None:
        output_path = (
            PROJECT_ROOT
            / "evidence"
            / f"{args.mode.lower()}_evaluation_{now.date().isoformat()}.json"
        )
    elif not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "output": str(output_path),
                "mode": report["mode"],
                "case_passed": f"{report['passed_count']}/{report['case_count']}",
                "classification_accuracy": report["mail_classification_accuracy"],
                "field_accuracy": report["field_extraction_accuracy"],
                "task_link_accuracy": report["task_link_accuracy"],
                "action_accuracy": report["action_step_accuracy"],
                "duration_ms": report["duration_ms"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
