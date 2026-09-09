from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from mailtaskagent import ui as ui_module
from mailtaskagent.config import Settings
from mailtaskagent.llm_client import MockMailAnalyzer
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow, load_mails


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
    assert ui_module._task_status_label("WAITING_REPLY") == "회신 대기"
    assert ui_module._task_status_label("FUTURE_STATUS") == "FUTURE_STATUS"
    assert ui_module._display_value(True, "reply_required") == "예"
    assert ui_module._display_value(None) == "-"


def test_agentic_trace_separates_agent_proposal_and_python_guard() -> None:
    assert ui_module._agentic_trace_phase("M-03 AGENT_ACTION_PROPOSAL")[0] == (
        "Agent Action Proposal"
    )
    assert ui_module._agentic_trace_phase("M-03 PYTHON_GUARD")[0] == "Python Guard"


def test_task_history_rows_include_changes_reason_and_user_decision(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "task-history.db")
    storage.initialize()
    task = storage.create_task_by_user(
        title="고객사 견적 검토",
        due_date="2026-09-01",
        importance=2,
    )
    storage.update_task_by_user(
        task["task_id"],
        title="고객사 최종 견적 검토",
        description="수정 견적 확인",
        due_date="2026-09-02",
        status="IN_PROGRESS",
        reply_required=True,
    )

    rows = ui_module._task_history_rows(storage, task["task_id"])

    assert len(rows) == 2
    assert rows[0]["Source Mail"] == "USER-DASHBOARD"
    assert rows[0]["Action"] == "기존 업무 변경"
    assert "업무 제목 고객사 견적 검토" in rows[0]["변경 전"]
    assert "업무 제목 고객사 최종 견적 검토" in rows[0]["변경 후"]
    assert rows[0]["판단 근거"] == "사용자가 Dashboard에서 Task를 직접 수정"
    assert rows[0]["사용자 결정"] == "사용자 직접 수정"
    assert rows[1]["사용자 결정"] == "사용자 직접 생성"


def test_demo_mode_uses_an_isolated_database_path(tmp_path) -> None:
    database_path = tmp_path / "mailtaskagent.db"

    assert (
        ui_module._database_path_for_mode(database_path, ui_module.OPERATION_MODE)
        == database_path
    )
    assert ui_module._database_path_for_mode(
        database_path, ui_module.DEMO_MODE
    ) == tmp_path / "mailtaskagent-demo.db"


def test_corrupt_operational_database_fails_closed_with_recovery_guidance(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "corrupt.db"
    database_path.write_bytes(b"not-a-sqlite-database")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "mailtaskagent-20260830T010203Z.db").write_bytes(b"backup")
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv(
        "GMAIL_CREDENTIALS_PATH", str(tmp_path / "missing-gmail-credentials.json")
    )
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "missing-gmail-token.json"))

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    app = _start_mode(app, "실제 업무 모드로 시작")

    assert not app.exception
    assert any(
        "업무 데이터베이스를 열 수 없습니다." in message.value
        for message in app.error
    )
    assert any(
        "원본 파일을 보존했습니다." in message.value for message in app.error
    )
    assert any(
        "mailtaskagent-20260830T010203Z.db" in message.value
        for message in app.caption
    )


def test_task_timeline_combines_inbound_and_outbound_lifecycle(tmp_path) -> None:
    settings = Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=tmp_path / "task-timeline.db",
        confidence_threshold=0.75,
    )
    storage = SQLiteStorage(settings.database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    for mail_id in ("MAIL-001", "MAIL-003", "MAIL-004"):
        workflow.process(mails[mail_id])

    task = storage.list_tasks()[0]
    rows = ui_module._task_mail_timeline_rows(storage, task)

    assert [row["direction"] for row in rows] == [
        "INBOUND",
        "OUTBOUND",
        "INBOUND",
    ]
    assert [row["action"] for row in rows] == [
        "CREATE_TASK",
        "SET_WAITING",
        "UPDATE_TASK",
    ]
    assert [row["status"] for row in rows] == [
        "TODO",
        "WAITING_REPLY",
        "IN_PROGRESS",
    ]
    assert rows[0]["sender"] == mails["MAIL-001"].sender
    assert rows[0]["recipients"] == mails["MAIL-001"].recipients
    assert rows[0]["body"] == mails["MAIL-001"].body

def _start_mode(app: AppTest, button_label: str) -> AppTest:
    buttons = [item for item in app.button if item.label == button_label]
    return buttons[0].click().run(timeout=60) if buttons else app


def _select_radio(
    app: AppTest, label: str, value: str, *, timeout: int = 60
) -> AppTest:
    radio = next(item for item in app.radio if item.label == label)
    return radio.set_value(value).run(timeout=timeout)


def _rendered_text(app: AppTest) -> str:
    """All text the screen actually paints, whatever widget produced it."""

    return "\n".join(
        [
            *(item.value for item in app.markdown),
            *(item.value for item in app.caption),
            *(item.value for item in app.subheader),
            *(item.value for item in app.info),
            *(item.value for item in app.warning),
            *(item.value for item in app.success),
        ]
    )


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
    home_text = _rendered_text(app)
    assert "업무 홈" in home_text
    assert "즉시 처리" in home_text


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
    initial_text = _rendered_text(app)
    for label, value in (
        ("처리된 Mail", "0/15건"),
        ("활성 업무", "0건"),
        ("기한·대기 주의", "0건"),
        ("Agent 확인 필요", "0건"),
    ):
        assert label in initial_text
        assert value in initial_text

    reset_button = next(button for button in app.button if button.label == "데모 DB 초기화")
    app = reset_button.click().run(timeout=60)
    assert not app.exception
    assert any(
        message.value
        == "데모 DB 초기화가 완료되었습니다. 실제 Gmail 업무 데이터에는 영향을 주지 않았습니다."
        for message in app.success
    )

    full_run_button = next(
        button
        for button in app.button
        if button.label.startswith("미처리·실패 합성 메일 전체 자동 정리")
    )
    full_run_button.click().run(timeout=120)

    assert not app.exception
    processed_text = _rendered_text(app)
    for label, value in (
        ("처리된 Mail", "15/15건"),
        ("활성 업무", "3건"),
        ("기한·대기 주의", "2건"),
        ("Agent 확인 필요", "7건"),
    ):
        assert label in processed_text
        assert value in processed_text
    assert any(
        message.value == "미처리 합성 메일 15건 자동 정리를 실행했습니다. 성공 15건"
        for message in app.success
    )
    assert any("Agentic Workflow Trace" in item.value for item in app.markdown)
    assert any(item.label == "Trace를 확인할 Mail" for item in app.selectbox)
    quality_text = _rendered_text(app)
    assert "Task Context Agent · RAG/ReAct Live 검증" in quality_text
    assert any(metric.label == "동일 업무 판단 신뢰도" for metric in app.metric)


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
    app = _select_radio(app, "운영 화면", "시스템 로그")
    assert not app.exception
    trace_text = _rendered_text(app)
    assert "이번 판단 한눈에 보기" in trace_text
    # The decision chain names every stage, including the recommended action,
    # the guard verdict and the final action.
    assert "1 · Mail 분석" in trace_text
    assert "2 · Task Context" in trace_text
    assert "3 · Agent 제안" in trace_text
    assert "4 · Python Guard" in trace_text
    assert "5 · 최종 실행" in trace_text
    # An escalation must never be presented as a success.
    assert "사용자 확인으로 이관" in trace_text
    # Confidence is labelled as the model's own score, with its threshold.
    assert "LLM 자기보고 신뢰도" in trace_text
    app = _select_radio(app, "주 메뉴", ui_module.TASKS_PAGE)

    assert not app.exception
    assert any(button.label == "상세 보기" for button in app.button)
    assert any(button.label == "완료 처리" for button in app.button)
    assert not app.dataframe

    detail_button = next(button for button in app.button if button.label == "상세 보기")
    app = detail_button.click().run(timeout=60)
    assert not app.exception
    # The dialog leads with the Task itself and splits the long content into
    # tabs instead of one continuous scroll.
    detail_tabs = [tab.label for tab in app.tabs]
    assert any(label.startswith("메일 흐름") for label in detail_tabs)
    assert "AI 회신 준비" in detail_tabs
    assert any(label.startswith("변경 기록") for label in detail_tabs)
    assert "업무 편집" in detail_tabs
    assert any(button.label == "회신 방식 판단" for button in app.button)
    assert not any("전송" in button.label for button in app.button)
    assert any(button.label == "변경 내용 저장" for button in app.button)

    reply_button = next(
        button for button in app.button if button.label == "회신 방식 판단"
    )
    app = reply_button.click().run(timeout=60)
    assert not app.exception
    rendered_reply = "\n".join(item.value for item in app.markdown)
    assert any(label in rendered_reply for label in ui_module.REPLY_ACTION_LABELS.values())
    assert not any("전송" in button.label for button in app.button)

    app = _select_radio(app, "주 메뉴", ui_module.HOME_PAGE)

    assert not app.exception
    assert any(button.label == "완료 처리" for button in app.button)
    home_text = _rendered_text(app)
    # Deadline pressure and importance evidence are shown as separate, named
    # facts rather than one grey sentence.
    assert "즉시 처리" in home_text
    assert "기한" in home_text
    assert "일 초과" in home_text
    complete_button = next(button for button in app.button if button.label == "완료 처리")
    app = complete_button.click().run(timeout=60)
    assert not app.exception
    assert any("업무를 완료했습니다." in message.value for message in app.success)


def test_task_detail_mail_flow_opens_one_mail_at_a_time(tmp_path, monkeypatch) -> None:
    """Clicking a mail flow row opens that mail, and only that mail."""

    database_path = tmp_path / "mail-flow.db"
    settings = Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=database_path,
        confidence_threshold=0.75,
    )
    storage = SQLiteStorage(database_path)
    workflow = MailTaskWorkflow(settings, storage, MockMailAnalyzer())
    mails = {
        mail.mail_id: mail
        for mail in load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    }
    for mail_id in ("MAIL-001", "MAIL-003", "MAIL-004"):
        workflow.process(mails[mail_id])
    task_id = storage.list_tasks()[0]["task_id"]

    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv(
        "GMAIL_CREDENTIALS_PATH", str(tmp_path / "missing-gmail-credentials.json")
    )
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "missing-gmail-token.json"))

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    app = _start_mode(app, "실제 업무 모드로 시작")
    app = _select_radio(app, "주 메뉴", ui_module.TASKS_PAGE)
    detail_button = next(button for button in app.button if button.label == "상세 보기")
    app = detail_button.click().run(timeout=60)
    assert not app.exception

    escape = ui_module.ui.esc
    first, last = mails["MAIL-001"], mails["MAIL-004"]

    # The newest mail is open on arrival, so the tab is never empty.
    opened = _rendered_text(app)
    assert escape(last.body) in opened
    assert escape(first.body) not in opened

    # Every mail in the flow has its own row control; there is no second list.
    row_keys = {
        f"open_mail_{task_id}_{mail_id}"
        for mail_id in ("MAIL-001", "MAIL-003", "MAIL-004")
    }
    assert row_keys <= {button.key for button in app.button}

    # Clicking a row opens that mail, with its participants and body.
    app = app.button(key=f"open_mail_{task_id}_MAIL-001").click().run(timeout=60)
    assert not app.exception
    switched = _rendered_text(app)
    assert escape(first.body) in switched
    assert escape(first.sender) in switched
    for recipient in first.recipients:
        assert escape(recipient) in switched
    # Only one mail body is expanded at a time.
    assert escape(last.body) not in switched


def test_gmail_readonly_source_empty_state(tmp_path, monkeypatch) -> None:
    credentials_path = tmp_path / "gmail_credentials.json"
    token_path = tmp_path / "gmail_token.json"
    credentials_path.write_text("{}", encoding="utf-8")
    token_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "gmail-ui.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(token_path))
    monkeypatch.setattr(ui_module, "_load_gmail_test_mails", lambda storage=None: [])

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    app = _start_mode(app, "실제 업무 모드로 시작")
    app = _select_radio(app, "주 메뉴", ui_module.MONITORING_PAGE)
    app = _select_radio(app, "운영 화면", "메일 처리 내역")

    assert not app.exception
    empty_text = _rendered_text(app)
    assert "Gmail 연결됨" in empty_text
    assert "현재 입력 Source에서 가져온 메일이 없습니다." in empty_text


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
    monkeypatch.setattr(
        ui_module,
        "_load_gmail_test_mails",
        lambda storage=None: gmail_mails,
    )

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    app = _start_mode(app, "실제 업무 모드로 시작")
    app = _select_radio(app, "주 메뉴", ui_module.AUTOMATION_PAGE)

    assert [tab.label for tab in app.tabs] == [
        "우선순위 기준",
        "광고·반복 메일 제외",
        "실행 주기",
    ]
    assert any(
        "VIP 발신자·고객사 도메인·중요 키워드" in item.value
        for item in app.markdown
    )

    assert not app.exception
    assert SQLiteStorage(database_path).is_processed(gmail_mails[0].mail_id)
    assert SQLiteStorage(database_path).get_operation_settings() == {
        "gmail_auto_sync_enabled": True,
        "gmail_sync_interval_minutes": 1,
    }
    assert any(toggle.label == "Agent 실행" for toggle in app.toggle)
    app = _select_radio(app, "주 메뉴", ui_module.HOME_PAGE)
    assert any(gmail_mails[0].subject in item.value for item in app.markdown)


def test_connected_operation_mode_renders_stored_mail_without_gmail_wait(
    tmp_path, monkeypatch
) -> None:
    credentials_path = tmp_path / "gmail_credentials.json"
    token_path = tmp_path / "gmail_token.json"
    database_path = tmp_path / "stored-mail-fast-start.db"
    credentials_path.write_text("{}", encoding="utf-8")
    token_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(token_path))

    settings = Settings(
        api_url="https://example.test",
        api_key="",
        model="mock",
        api_version="test",
        timeout_seconds=1,
        use_mock=True,
        database_path=database_path,
        confidence_threshold=0.75,
    )
    gmail_mail = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[0].model_copy(
        update={
            "mail_id": "GMAIL-stored-message",
            "conversation_id": "GMAIL-THREAD-stored-thread",
        }
    )
    MailTaskWorkflow(settings, SQLiteStorage(database_path), MockMailAnalyzer()).process(
        gmail_mail
    )
    restored = ui_module._load_stored_mail_inputs(SQLiteStorage(database_path))
    assert [mail.mail_id for mail in restored] == ["GMAIL-stored-message"]
    assert restored[0].direction.value == "INBOUND"

    def fail_if_gmail_is_called(storage=None):
        raise AssertionError("Stored operational view must not call Gmail on first paint")

    monkeypatch.setattr(ui_module, "_load_gmail_test_mails", fail_if_gmail_is_called)

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    app = _start_mode(app, "실제 업무 모드로 시작")

    assert not app.exception
    assert any(gmail_mail.subject in item.value for item in app.markdown)


def test_operation_monitoring_is_separate_from_task_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "monitoring.db"))
    monkeypatch.setenv("COMPANY_LLM_USE_MOCK", "true")
    monkeypatch.setenv(
        "GMAIL_CREDENTIALS_PATH", str(tmp_path / "missing-gmail-credentials.json")
    )
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "missing-gmail-token.json"))

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=60)
    app = _start_mode(app, "실제 업무 모드로 시작")

    home_text = _rendered_text(app)
    assert "업무 홈" in home_text
    assert "Gmail 자동 실행 기록" not in home_text

    app = _select_radio(app, "주 메뉴", ui_module.MONITORING_PAGE)

    assert not app.exception
    rendered = _rendered_text(app)
    assert "운영 상태" in rendered
    assert "Gmail 자동 실행 기록" in rendered
    # The acceptance-test figures stay on the monitoring page. Sync run counts
    # only appear once a run exists, so they are not asserted on a fresh DB.
    for label in ("Gmail 실메일 수용시험", "수신", "통과", "실패", "대기"):
        assert label in rendered
