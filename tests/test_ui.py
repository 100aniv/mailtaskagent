from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_product_dashboard_and_full_mock_mail_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ui-smoke.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "업무 현황",
        "메일 처리함",
        "확인 필요",
        "운영 로그",
        "품질 검증",
        "데모 도구",
    ]
    assert [(metric.label, metric.value) for metric in app.metric[:4]] == [
        ("처리된 Mail", "0/15건"),
        ("활성 업무", "0건"),
        ("기한·대기 주의", "0건"),
        ("Agent 확인 필요", "0건"),
    ]

    full_run_button = next(
        button
        for button in app.button
        if button.label.startswith("미처리·실패 합성 메일 전체 자동 정리")
    )
    full_run_button.click().run(timeout=120)

    assert not app.exception
    assert [(metric.label, metric.value) for metric in app.metric[:4]] == [
        ("처리된 Mail", "15/15건"),
        ("활성 업무", "3건"),
        ("기한·대기 주의", "2건"),
        ("Agent 확인 필요", "7건"),
    ]
    assert any(
        message.value == "미처리 합성 메일 15건 자동 정리를 실행했습니다. 성공 15건"
        for message in app.success
    )
