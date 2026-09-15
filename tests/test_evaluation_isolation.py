"""MOCK evaluation must not reach the company LLM.

The runner used to swap only the mail analyzer, leaving settings.use_mock at
whatever the environment said. The workflow picks its Task Context agent from
that flag, so a MOCK run on a LIVE-configured machine still called the real
agent — which made the published "deterministic mock" comparison neither
deterministic nor free.
"""

from __future__ import annotations

import sys
from dataclasses import replace

import pytest

from mailtaskagent import evaluation_cli
from mailtaskagent.config import load_settings
from mailtaskagent.evaluation import run_scenario_evaluation
from mailtaskagent.llm_client import MockMailAnalyzer
from mailtaskagent.task_context_agent import (
    AzureTaskContextAgent,
    MockTaskContextAgent,
    build_task_context_agent,
)


def test_mock_settings_select_the_mock_task_context_agent():
    settings = load_settings()
    assert isinstance(
        build_task_context_agent(settings.__class__(**{**settings.__dict__, "use_mock": True})),
        MockTaskContextAgent,
    )


def test_mock_mode_never_constructs_the_company_agent(monkeypatch, tmp_path):
    """Running --mode MOCK must not instantiate the Azure agent even once."""

    def refuse(settings):
        raise AssertionError(
            "MOCK evaluation constructed AzureTaskContextAgent; it must stay offline"
        )

    monkeypatch.setattr(
        "mailtaskagent.task_context_agent.AzureTaskContextAgent.__init__", refuse
    )

    captured = {}

    def capture(settings, analyzer, *, mode, suite="core"):
        captured["use_mock"] = settings.use_mock
        return {
            "mode": mode,
            "suite": suite,
            "case_count": 0,
            "passed_count": 0,
            "scenario_pass_rate": 1.0,
            "action_step_accuracy": 1.0,
            "review_rate": 0.0,
            "automatic_rate": 0.0,
            "total_action_steps": 0,
            "duration_ms": 0,
            "rows": [],
            "mail_classification_accuracy": 1.0,
            "field_extraction_accuracy": 1.0,
            "task_link_accuracy": 1.0,
        }

    monkeypatch.setattr(evaluation_cli, "run_scenario_evaluation", capture)
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluation_cli", "--mode", "MOCK", "--output", str(tmp_path / "out.json")],
    )
    evaluation_cli.main()

    assert captured["use_mock"] is True, (
        "MOCK mode handed the workflow settings that still allow the company agent"
    )


def test_direct_mock_evaluation_never_constructs_the_company_agent(monkeypatch):
    """The Streamlit/direct-call path must be as isolated as the CLI path."""

    def refuse(self, settings):
        raise AssertionError(
            "direct MOCK evaluation constructed AzureTaskContextAgent"
        )

    monkeypatch.setattr(AzureTaskContextAgent, "__init__", refuse)
    live_settings = replace(load_settings(), use_mock=False)

    report = run_scenario_evaluation(
        live_settings,
        MockMailAnalyzer(),
        mode="MOCK",
        suite="deliberation",
    )

    assert report["mode"] == "MOCK"
    assert report["passed_count"] == report["case_count"] == 4


def test_direct_live_evaluation_rejects_mock_settings():
    settings = replace(load_settings(), use_mock=True)

    with pytest.raises(ValueError, match="LIVE evaluation requires"):
        run_scenario_evaluation(
            settings,
            MockMailAnalyzer(),
            mode="LIVE",
            suite="deliberation",
        )


def test_live_mode_keeps_the_company_agent(monkeypatch):
    """The same guard must not quietly turn LIVE into a mock run.

    Constructing the real agent needs an API key, which a clean checkout does
    not have, so this asserts which class is selected rather than whether this
    machine happens to be configured for it.
    """
    built: list[object] = []

    def record(self, settings):
        built.append(settings)

    monkeypatch.setattr(AzureTaskContextAgent, "__init__", record)

    settings = load_settings()
    live = settings.__class__(**{**settings.__dict__, "use_mock": False})
    agent = build_task_context_agent(live)

    assert isinstance(agent, AzureTaskContextAgent)
    assert built, "the company agent should have been constructed for LIVE"
