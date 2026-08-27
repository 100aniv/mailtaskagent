from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from mailtaskagent import ui as ui_module


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


def test_gmail_readonly_source_empty_state(tmp_path, monkeypatch) -> None:
    credentials_path = tmp_path / "gmail_credentials.json"
    token_path = tmp_path / "gmail_token.json"
    credentials_path.write_text("{}", encoding="utf-8")
    token_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "gmail-ui.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(token_path))
    monkeypatch.setattr(ui_module, "_load_gmail_test_mails", lambda: [])

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    source_radio = next(radio for radio in app.radio if radio.label == "입력 Source")
    assert source_radio.options == ["합성 데모", "Gmail 테스트"]

    source_radio.set_value("Gmail 테스트").run(timeout=60)

    assert not app.exception
    assert any(
        "Gmail OAuth · 읽기 전용 연결됨" in message.value
        for message in app.success
    )
    assert any(
        "현재 입력 Source에서 가져온 메일이 없습니다." in message.value
        for message in app.info
    )
