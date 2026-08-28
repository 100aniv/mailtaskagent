from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from mailtaskagent import ui as ui_module
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import load_mails


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
    buttons = [item for item in app.button if item.label == button_label]
    return buttons[0].click().run(timeout=60) if buttons else app


def _select_radio(
    app: AppTest, label: str, value: str, *, timeout: int = 60
) -> AppTest:
    radio = next(item for item in app.radio if item.label == label)
    return radio.set_value(value).run(timeout=timeout)


def test_mode_entry_separates_operational_and_demo_navigation(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mode-entry.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv(
        "GMAIL_CREDENTIALS_PATH", str(tmp_path / "missing-gmail-credentials.json")
    )
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "missing-gmail-token.json"))

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)

    assert {button.label for button in app.button} >= {
        "실제 업무 모드로 시작",
        "MVP 시연 모드로 시작",
    }

    app = _start_mode(app, "실제 업무 모드로 시작")

    assert not app.exception
    navigation = next(radio for radio in app.radio if radio.label == "주 메뉴")
    assert navigation.options == ui_module.OPERATION_PAGES
    assert not app.tabs
    assert not any(button.label == "데모 DB 초기화" for button in app.button)
    assert any(button.label == "전체 업무 보기" for button in app.button)
    assert any("긴급 업무" in item.value for item in app.markdown)


def test_product_dashboard_and_full_mock_mail_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ui-smoke.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv(
        "GMAIL_CREDENTIALS_PATH", str(tmp_path / "missing-gmail-credentials.json")
    )
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "missing-gmail-token.json"))

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


def test_operation_mode_renders_explainable_priority_and_direct_completion(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "operation-priority.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv(
        "GMAIL_CREDENTIALS_PATH", str(tmp_path / "missing-gmail-credentials.json")
    )
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "missing-gmail-token.json"))

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    app = _start_mode(app, "실제 업무 모드로 시작")
    app = _select_radio(app, "주 메뉴", ui_module.MONITORING_PAGE)
    app = _select_radio(app, "운영 화면", "메일 처리 내역")
    batch_button = next(
        button for button in app.button if button.label.startswith("미처리 메일 전체 분류")
    )
    app = batch_button.click().run(timeout=120)
    app = _select_radio(app, "주 메뉴", ui_module.TASKS_PAGE)

    assert not app.exception
    assert any(button.label == "상세 보기" for button in app.button)
    assert any(button.label == "완료 처리" for button in app.button)
    assert not app.dataframe

    app = _select_radio(app, "주 메뉴", ui_module.HOME_PAGE)

    assert not app.exception
    assert any(button.label == "완료 처리" for button in app.button)
    assert any("우선순위 근거 ·" in caption.value for caption in app.caption)
    assert any("긴급 업무" in item.value for item in app.markdown)
    complete_button = next(button for button in app.button if button.label == "완료 처리")
    app = complete_button.click().run(timeout=60)
    assert not app.exception
    assert any("업무를 완료했습니다." in message.value for message in app.success)


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
    app = _select_radio(app, "주 메뉴", ui_module.MONITORING_PAGE)
    app = _select_radio(app, "운영 화면", "메일 처리 내역")

    assert not app.exception
    assert any("Gmail 연결됨" in message.value for message in app.markdown)
    assert any(
        "현재 입력 Source에서 가져온 메일이 없습니다." in message.value
        for message in app.info
    )


def test_connected_operation_mode_runs_gmail_agent_by_default(
    tmp_path, monkeypatch
) -> None:
    credentials_path = tmp_path / "gmail_credentials.json"
    token_path = tmp_path / "gmail_token.json"
    database_path = tmp_path / "gmail-auto-sync.db"
    credentials_path.write_text("{}", encoding="utf-8")
    token_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(token_path))
    gmail_mails = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[:1]
    monkeypatch.setattr(ui_module, "_load_gmail_test_mails", lambda: gmail_mails)

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    app = _start_mode(app, "실제 업무 모드로 시작")
    app = _select_radio(app, "주 메뉴", ui_module.AUTOMATION_PAGE)

    assert [tab.label for tab in app.tabs] == [
        "⭐ 중요도 기준",
        "🚫 광고·반복 메일 제외",
        "⚙️ 실행 주기",
    ]
    assert any(
        "VIP 발신자, 고객사 도메인, 중요 키워드" in item.value
        for item in app.markdown
    )

    assert not app.exception
    assert SQLiteStorage(database_path).is_processed(gmail_mails[0].mail_id)
    assert SQLiteStorage(database_path).get_operation_settings() == {
        "gmail_auto_sync_enabled": True,
        "gmail_sync_interval_minutes": 1,
    }
    assert any(toggle.label == "자동 정리 실행" for toggle in app.toggle)
    app = _select_radio(app, "주 메뉴", ui_module.HOME_PAGE)
    assert any(gmail_mails[0].subject in item.value for item in app.markdown)


def test_operation_monitoring_is_separate_from_task_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "monitoring.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv(
        "GMAIL_CREDENTIALS_PATH", str(tmp_path / "missing-gmail-credentials.json")
    )
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "missing-gmail-token.json"))

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    app = _start_mode(app, "실제 업무 모드로 시작")

    assert any(item.value == "업무 홈" for item in app.subheader)
    assert not any("Gmail 자동 실행 기록" in item.value for item in app.markdown)

    app = _select_radio(app, "주 메뉴", ui_module.MONITORING_PAGE)

    assert not app.exception
    assert any(item.value == "운영 상태" for item in app.subheader)
    assert any("Gmail 자동 실행 기록" in item.value for item in app.markdown)
    rendered = "\n".join(item.value for item in app.markdown)
    for label in (
        "최근 실행",
        "신규 메일",
        "처리 성공",
        "처리 실패",
        "수신",
        "통과",
        "실패",
        "대기",
    ):
        assert label in rendered
