from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from mailtaskagent import ui as ui_module


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_history_change_rows_show_only_business_field_changes() -> None:
    rows = ui_module._history_change_rows(
        {
            "title": "주간 현황 보고서 작성",
            "due_date": "2026-08-31",
            "status": "TODO",
            "updated_at": "2026-08-27T13:28:15+00:00",
        },
        {
            "title": "주간 현황 보고서 작성",
            "due_date": "2026-09-02",
            "status": "TODO",
            "updated_at": "2026-08-27T13:28:18+00:00",
        },
    )

    assert rows == [
        {"변경 항목": "기한", "변경 전": "2026-08-31", "변경 후": "2026-09-02"}
    ]


def test_display_value_localizes_status_and_boolean() -> None:
    assert ui_module._display_value("WAITING_REPLY", "status") == "회신 대기"
    assert ui_module._display_value(True, "reply_required") == "예"
    assert ui_module._display_value(None) == "-"


def test_demo_mode_uses_an_isolated_database_path(tmp_path) -> None:
    database_path = tmp_path / "mailtaskagent.db"

    assert (
        ui_module._database_path_for_mode(database_path, ui_module.OPERATION_MODE)
        == database_path
    )
    assert ui_module._database_path_for_mode(
        database_path, ui_module.DEMO_MODE
    ) == tmp_path / "mailtaskagent-demo.db"


def _start_mode(app: AppTest, button_label: str) -> AppTest:
    button = next(item for item in app.button if item.label == button_label)
    return button.click().run(timeout=60)


def test_mode_entry_separates_operational_and_demo_navigation(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mode-entry.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)

    assert {button.label for button in app.button} >= {
        "실제 업무 모드로 시작",
        "MVP 시연 모드로 시작",
    }

    app = _start_mode(app, "실제 업무 모드로 시작")

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "업무 현황",
        "메일 처리함",
        "확인 필요",
        "운영 로그",
    ]
    assert not any(button.label == "데모 DB 초기화" for button in app.button)


def test_product_dashboard_and_full_mock_mail_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ui-smoke.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    app = _start_mode(app, "MVP 시연 모드로 시작")

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
    app = _start_mode(app, "실제 업무 모드로 시작")
    source_radio = next(radio for radio in app.radio if radio.label == "메일 연결")
    assert source_radio.options == ["Gmail 테스트", "합성 데모"]

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
