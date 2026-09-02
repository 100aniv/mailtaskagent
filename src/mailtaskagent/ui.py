from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from time import perf_counter

import pandas as pd
import streamlit as st

from mailtaskagent.config import PROJECT_ROOT, load_settings
from mailtaskagent.evaluation import load_saved_evaluation_report, run_scenario_evaluation
from mailtaskagent.gmail_source import (
    GmailReadOnlySource,
    build_gmail_service,
    load_gmail_source_settings,
)
from mailtaskagent.gmail_pilot import evaluate_gmail_pilot, load_gmail_pilot_cases
from mailtaskagent.llm_client import MockMailAnalyzer, build_analyzer
from mailtaskagent.mail_filters import (
    MailFilterRuleType,
    build_operational_analyzer,
    match_mail_filter_rule,
)
from mailtaskagent.manual_benchmark import (
    calculate_manual_benchmark_result,
    load_manual_benchmark_cases,
    save_manual_benchmark_evidence,
)
from mailtaskagent.models import AgentAction, MailDirection, MailInput, ReviewDecision
from mailtaskagent.operations import MailSyncService
from mailtaskagent.priority import (
    PRIORITY_PRESENTATION,
    PriorityLevel,
    PriorityRuleType,
    calculate_task_priority,
)
from mailtaskagent.slack_notifications import load_slack_notification_settings
from mailtaskagent.storage import SQLiteStorage
from mailtaskagent.workflow import MailTaskWorkflow, load_mails


ACTION_LABELS = {
    AgentAction.CREATE_TASK.value: "새 업무 생성",
    AgentAction.UPDATE_TASK.value: "기존 업무 변경",
    AgentAction.LINK_TO_TASK.value: "기존 업무에 연결",
    AgentAction.SET_WAITING.value: "회신 대기로 전환",
    AgentAction.MARK_COMPLETED.value: "업무 완료 처리",
    AgentAction.ASK_USER.value: "사용자 확인 요청",
    AgentAction.IGNORE.value: "업무 대상에서 제외",
}

STATUS_LABELS = {
    "TODO": "할 일",
    "IN_PROGRESS": "진행 중",
    "WAITING_REPLY": "회신 대기",
    "COMPLETED": "완료",
    "CANCELLED": "취소",
}

INTENT_LABELS = {
    "NEW_TASK": "신규 업무 요청",
    "DUE_DATE_CHANGE": "기한 변경",
    "TASK_UPDATE": "업무 내용 변경",
    "WAITING": "자료 요청·회신 대기",
    "INFORMATION_RECEIVED": "후속 정보 도착",
    "COMPLETION": "완료 관련",
    "CANCELLATION": "취소 관련",
    "NON_TASK": "업무 아님·공지",
    "UNCERTAIN": "사용자 확인 필요",
}


def _initialize_storage_or_stop(storage: SQLiteStorage) -> None:
    """Fail closed with recovery guidance when the local SQLite file is damaged."""

    try:
        storage.initialize()
    except sqlite3.DatabaseError:
        st.error(
            "업무 데이터베이스를 열 수 없습니다. 자동 처리를 중지하고 원본 파일을 보존했습니다."
        )
        st.info(
            "앱과 자동 동기화를 모두 종료한 뒤, 무결성이 확인된 최신 백업으로 복원하세요. "
            "자세한 절차는 Docs/IMPLEMENTATION/09_Post_MVP_운영가이드.md의 DB 복구 항목에 있습니다."
        )
        backup_dir = storage.path.parent / "backups"
        backups = sorted(
            backup_dir.glob("mailtaskagent-*.db"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        if backups:
            st.caption(f"최근 복구용 백업 후보 · {backups[0].name}")
        st.stop()


DEMO_SCENARIOS = {
    "create_update": {
        "title": "신규 업무 → 기한 변경",
        "description": "메일 요청으로 업무를 만들고 후속 메일의 변경 기한을 반영합니다.",
        "mail_ids": ["MAIL-001", "MAIL-002"],
    },
    "waiting_resume": {
        "title": "회신 대기 → 업무 재개",
        "description": "자료를 요청하면 회신 대기로 바꾸고, 자료가 오면 진행 중으로 복귀합니다.",
        "mail_ids": ["MAIL-001", "MAIL-003", "MAIL-004"],
    },
    "human_review": {
        "title": "애매한 메일 → 사용자 확인",
        "description": "후보가 둘이면 자동 변경을 멈추고 사용자의 최종 선택을 기다립니다.",
        "mail_ids": ["MAIL-001", "MAIL-008", "MAIL-006"],
    },
    "completion_review": {
        "title": "완료 제안 → 사용자 승인",
        "description": "완료 근거가 있어도 자동 완료하지 않고 사용자의 최종 승인을 기다립니다.",
        "mail_ids": ["MAIL-001", "MAIL-009"],
    },
}

SYNTHETIC_MAIL_SOURCE = "합성 데모"
GMAIL_TEST_SOURCE = "Gmail 테스트"
OPERATION_MODE = "실제 업무 모드"
DEMO_MODE = "MVP 시연 모드"
HOME_PAGE = "🏠 홈"
TASKS_PAGE = "✅ 내 업무"
REVIEW_PAGE = "🔔 검토 요청"
AUTOMATION_PAGE = "⚙️ 자동화 설정"
MONITORING_PAGE = "📊 운영 상태"
SETTINGS_PAGE = "🔧 설정"
OPERATION_PAGES = [
    HOME_PAGE,
    TASKS_PAGE,
    REVIEW_PAGE,
    AUTOMATION_PAGE,
    MONITORING_PAGE,
    SETTINGS_PAGE,
]

HISTORY_FIELD_LABELS = {
    "title": "업무 제목",
    "description": "업무 설명",
    "requester": "요청자",
    "due_date": "기한",
    "reply_required": "회신 필요",
    "status": "상태",
    "waiting_since": "회신 대기 시작",
    "importance_override": "사용자 중요도",
}

PRIORITY_RULE_LABELS = {
    PriorityRuleType.SENDER_EMAIL.value: "정확한 발신자 이메일",
    PriorityRuleType.SENDER_DOMAIN.value: "고객사·조직 도메인",
    PriorityRuleType.KEYWORD.value: "제목·업무 키워드",
}

MAIL_FILTER_RULE_LABELS = {
    MailFilterRuleType.SENDER_EMAIL.value: "정확한 발신자 이메일",
    MailFilterRuleType.SENDER_DOMAIN.value: "발신자 도메인",
    MailFilterRuleType.SUBJECT_KEYWORD.value: "제목 키워드",
}

USER_DECISION_LABELS = {
    ReviewDecision.APPROVE_PROPOSAL.value: "Agent 제안 승인",
    ReviewDecision.LINK_EXISTING.value: "기존 업무 연결",
    ReviewDecision.CREATE_NEW.value: "신규 업무 생성",
    ReviewDecision.IGNORE.value: "반영하지 않음",
    "MANUAL_CREATE": "사용자 직접 생성",
    "MANUAL_EDIT": "사용자 직접 수정",
    "PRIORITY_OVERRIDE": "사용자 중요도 지정",
}


def _display_value(value, field: str | None = None) -> str:
    if value is None or value == "":
        return "-"
    if field == "status":
        return STATUS_LABELS.get(str(value), str(value))
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _history_change_rows(before: dict | None, after: dict | None) -> list[dict]:
    before = before or {}
    after = after or {}
    rows = []
    for field, label in HISTORY_FIELD_LABELS.items():
        before_value = before.get(field)
        after_value = after.get(field)
        if before_value == after_value:
            continue
        rows.append(
            {
                "변경 항목": label,
                "변경 전": _display_value(before_value, field),
                "변경 후": _display_value(after_value, field),
            }
        )
    return rows


def _user_decision_label(user_decision: dict | None) -> str:
    if not user_decision:
        return "자동 반영"
    decision = user_decision.get("decision")
    return USER_DECISION_LABELS.get(decision, decision or "사용자 확인")


def _task_history_rows(storage, task_id: str, *, limit: int = 20) -> list[dict]:
    """Build a concise user-facing audit trail for one Task."""

    context = storage.get_task_context(task_id, history_limit=limit)
    if not context:
        return []
    rows = []
    for history in context["recent_histories"]:
        before = _parse_json(history.get("before_json"))
        after = _parse_json(history.get("after_json"))
        user_decision = _parse_json(history.get("user_decision"))
        changes = _history_change_rows(before, after)
        before_summary = "; ".join(
            f"{change['변경 항목']} {change['변경 전']}" for change in changes
        )
        after_summary = "; ".join(
            f"{change['변경 항목']} {change['변경 후']}" for change in changes
        )
        rows.append(
            {
                "처리 시각": datetime.fromisoformat(history["created_at"])
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S"),
                "Source Mail": history["mail_id"],
                "Action": ACTION_LABELS.get(history["action"], history["action"]),
                "변경 전": before_summary or "-",
                "변경 후": after_summary or "메일 연결·처리 기록",
                "판단 근거": history["reason"],
                "사용자 결정": _user_decision_label(user_decision),
            }
        )
    return rows


def _detail_rows(details) -> list[dict]:
    if not isinstance(details, dict):
        return []
    return [
        {"항목": key.replace("_", " "), "값": _display_value(value)}
        for key, value in details.items()
    ]


def _task_mail_timeline_rows(storage, task: dict, *, limit: int = 50) -> list[dict]:
    """Build a user-facing, chronological mail lifecycle for one Task."""

    results_by_mail = {
        item["mail_id"]: item
        for item in storage.list_processing_results()
        if item.get("task_id") == task["task_id"]
    }
    histories_by_mail = {}
    for history in storage.list_histories():
        if history.get("task_id") != task["task_id"]:
            continue
        histories_by_mail.setdefault(history["mail_id"], history)

    rows = []
    mails = reversed(
        storage.list_thread_mails(task["conversation_id"], limit=limit)
    )
    for mail in mails:
        history = histories_by_mail.get(mail["mail_id"])
        result = results_by_mail.get(mail["mail_id"])
        action = None
        if history:
            action = history.get("action")
        elif result:
            action = result.get("action")
        after = _parse_json(history.get("after_json")) if history else None
        direction = mail["direction"]
        counterpart = (
            mail["sender"]
            if direction == "INBOUND"
            else ", ".join(mail.get("recipients") or []) or "수신자 정보 없음"
        )
        rows.append(
            {
                "mail_id": mail["mail_id"],
                "occurred_at": mail["occurred_at"],
                "direction": direction,
                "direction_label": "🔵 받은 메일" if direction == "INBOUND" else "🟣 보낸 메일",
                "counterpart": counterpart,
                "subject": mail["subject"],
                "action": action,
                "action_label": ACTION_LABELS.get(action, action or "처리 기록 없음"),
                "status": after.get("status") if isinstance(after, dict) else None,
            }
        )
    return rows


def _render_mode_entry(*, gmail_connected: bool = False) -> str | None:
    selected_mode = st.session_state.get("app_mode")
    if selected_mode in {OPERATION_MODE, DEMO_MODE}:
        return selected_mode

    if gmail_connected:
        st.session_state["app_mode"] = OPERATION_MODE
        return OPERATION_MODE

    st.title("MailTaskAgent")
    st.write("사용 목적에 맞는 화면을 선택하세요. 언제든 사이드바에서 다시 바꿀 수 있습니다.")
    operation_col, demo_col = st.columns(2)
    with operation_col:
        with st.container(border=True):
            st.markdown("### 실제 업무 모드")
            st.write("홈에서 오늘 할 일과 검토 대기를 보고, 업무·검토함·설정만 사용합니다.")
            st.caption("Gmail 읽기 전용 파일럿을 위한 실제 사용 화면입니다.")
            if st.button(
                "실제 업무 모드로 시작",
                type="primary",
                width="stretch",
            ):
                st.session_state["app_mode"] = OPERATION_MODE
                st.rerun()
    with demo_col:
        with st.container(border=True):
            st.markdown("### MVP 시연 모드")
            st.write("합성 시나리오, 품질 검증, 기술 설정과 데모 초기화 도구를 함께 표시합니다.")
            st.caption("멘토 시연과 AI Master 검증 증적 확인에 사용합니다.")
            if st.button("MVP 시연 모드로 시작", width="stretch"):
                st.session_state["app_mode"] = DEMO_MODE
                st.rerun()
    st.info(
        "두 모드는 동일한 Agent Core를 사용하지만 실제 업무와 시연 데이터는 분리 저장합니다. "
        "회사 운영 전환 시에는 MVP 시연 모드를 제거할 수 있습니다."
    )
    return None


def _database_path_for_mode(database_path: Path | str, app_mode: str) -> Path:
    path = Path(database_path)
    if app_mode != DEMO_MODE:
        return path
    return path.with_name(f"{path.stem}-demo{path.suffix}")


def _gmail_connection_summary() -> dict:
    gmail_settings = load_gmail_source_settings()
    return {
        "credentials_ready": gmail_settings.credentials_path.exists(),
        "token_ready": gmail_settings.token_path.exists(),
        "query": gmail_settings.query,
        "max_results": gmail_settings.max_results,
    }


def _load_gmail_test_mails(storage=None):
    gmail_settings = load_gmail_source_settings()
    tracked_conversation_ids = (
        [task["conversation_id"] for task in storage.list_tasks()]
        if storage is not None
        else []
    )
    source = GmailReadOnlySource(
        build_gmail_service(gmail_settings),
        gmail_settings,
        tracked_conversation_ids=tracked_conversation_ids,
    )
    return source.load()


def _load_stored_mail_inputs(storage, *, limit: int = 100) -> list[MailInput]:
    """Restore the already-processed mailbox view without a Gmail network call."""

    mails = []
    rows = [
        row
        for row in storage.list_mails()
        if row["mail_id"].startswith("GMAIL-")
    ][:limit]
    for row in rows:
        direction = MailDirection(row["direction"])
        occurred_at = datetime.fromisoformat(row["occurred_at"])
        timestamp = (
            {"received_at": occurred_at}
            if direction == MailDirection.INBOUND
            else {"sent_at": occurred_at}
        )
        mails.append(
            MailInput(
                mail_id=row["mail_id"],
                conversation_id=row["conversation_id"],
                direction=direction,
                sender=row["sender"],
                recipients=row["recipients"],
                subject=row["subject"],
                body=row["body"],
                **timestamp,
            )
        )
    return mails


class _GmailSyncSource:
    def __init__(self, storage, cached_mails=None) -> None:
        self.storage = storage
        self.loaded_mails = cached_mails

    def load(self):
        if self.loaded_mails is None:
            self.loaded_mails = _load_gmail_test_mails(self.storage)
        return list(self.loaded_mails)


def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        html, body, [class*="css"] {font-family: "Noto Sans KR", "Malgun Gothic", sans-serif;}
        .stApp {background: #f8fafc; color: #172033;}
        .block-container {padding-top: 4.25rem; padding-bottom: 3rem; max-width: 1320px;}
        [data-testid="stSidebar"] {background: #17223b; border-right: 0;}
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label {color: #e7eefc;}
        [data-testid="stSidebar"] button {
            border-color: #435270; color: #e7eefc; background: #24314e;
        }
        [data-testid="stSidebar"] hr {border-color: #334563;}
        [data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] {gap: 5px;}
        [data-testid="stSidebar"] [data-testid="stRadioOption"] {
            min-height: 42px; padding: 8px 11px; border-radius: 10px;
        }
        [data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {
            background: #2c3b5d;
        }
        [data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div > div:first-child {
            display: none;
        }
        [data-testid="stMetric"] {
            background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
            padding: 15px 17px; box-shadow: none;
        }
        [data-testid="stMetricLabel"] {color: #475569;}
        button[data-baseweb="tab"] {font-weight: 600; padding-left: 14px; padding-right: 14px;}
        button[data-baseweb="tab"][aria-selected="true"] {color: #3157d5;}
        button[kind="primary"] {background: #4263eb !important; border-color: #4263eb !important;}
        button[kind="primary"]:hover {background: #3451c7 !important; border-color: #3451c7 !important;}
        div[data-testid="stStatusWidget"] {border-radius: 12px;}
        [data-testid="stVerticalBlockBorderWrapper"] {border-color: #e2e8f0; border-radius: 12px;}
        .mail-card {
            padding: 16px 18px; border-radius: 14px; background: #ffffff;
            border: 1px solid #dde5f1; margin-bottom: 12px;
        }
        .mail-card small {color: #64748b;}
        .priority-title {font-size: 1rem; font-weight: 700; color: #17213a;}
        .priority-meta {font-size: 0.86rem; color: #64748b; margin-top: 0.2rem;}
        .operation-status-bar {
            display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
            background: #ffffff; border: 1px solid #dbe3ef; border-radius: 10px;
            padding: 10px 14px; margin: 0.35rem 0 1rem 0; color: #475569;
            font-size: 0.86rem;
        }
        .operation-status-bar strong {color: #172033; font-weight: 700;}
        .operation-status-bar .status-dot {
            width: 9px; height: 9px; border-radius: 50%; display: inline-block;
            margin-right: 7px; background: #16a34a;
        }
        .operation-status-bar.warning .status-dot {background: #f59e0b;}
        .operation-status-bar.danger .status-dot {background: #dc2626;}
        .operation-status-bar .status-separator {color: #cbd5e1;}
        .work-summary-grid {
            display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr));
            gap: 10px; margin: 0.2rem 0 1.25rem 0;
        }
        .work-summary-card {
            background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
            padding: 14px 16px;
        }
        .work-summary-label {font-size: 0.84rem; color: #64748b; margin-bottom: 7px;}
        .work-summary-value {font-size: 1.55rem; line-height: 1; font-weight: 750; color: #172033;}
        .work-summary-card.red {border-top: 3px solid #dc2626;}
        .work-summary-card.orange {border-top: 3px solid #f97316;}
        .work-summary-card.yellow {border-top: 3px solid #eab308;}
        .work-summary-card.purple {border-top: 3px solid #7c3aed;}
        @media (max-width: 900px) {
            .work-summary-grid {grid-template-columns: repeat(2, minmax(120px, 1fr));}
            .operation-status-bar {gap: 10px;}
            .operation-status-bar .status-separator {display: none;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _action_label(action: str) -> str:
    return f"{ACTION_LABELS.get(action, action)} · {action}"


def _friendly_mail(mail) -> str:
    return f"{mail.mail_id} · {mail.subject}"


def _candidate_frame(candidates: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(candidates)
    if "match_score" not in frame:
        frame["match_score"] = 0.0
    if "match_reason" not in frame:
        frame["match_reason"] = "기존 처리 결과"
    frame["매칭 점수"] = frame["match_score"].apply(lambda value: f"{value:.0%}")
    frame = frame.rename(
        columns={
            "task_id": "Task ID",
            "title": "업무 제목",
            "status": "상태",
            "due_date": "기한",
            "match_reason": "매칭 근거",
        }
    )
    return frame[["Task ID", "업무 제목", "상태", "기한", "매칭 점수", "매칭 근거"]]


def _parse_json(value):
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _task_attention(task: dict) -> str:
    status = task.get("status")
    today = date.today()
    if status not in {"COMPLETED", "CANCELLED"} and task.get("due_date"):
        due_date = date.fromisoformat(task["due_date"])
        days = (due_date - today).days
        if days < 0:
            return f"기한 {abs(days)}일 초과"
        if days <= 3:
            return "오늘 기한" if days == 0 else f"기한 {days}일 남음"
    if status == "WAITING_REPLY" and task.get("waiting_since"):
        waiting_date = datetime.fromisoformat(task["waiting_since"]).date()
        waiting_days = (today - waiting_date).days
        if waiting_days >= 3:
            return f"회신 {waiting_days}일 대기"
    return "-"


def _task_priority(task: dict, priority_level: PriorityLevel | None = None) -> tuple[int, str, str]:
    if priority_level is not None:
        return int(priority_level.value[-1]), task.get("due_date") or "9999-12-31", task["task_id"]
    attention = _task_attention(task)
    if "초과" in attention:
        rank = 0
    elif "오늘" in attention or "남음" in attention:
        rank = 1
    elif "대기" in attention:
        rank = 2
    else:
        rank = 3
    return rank, task.get("due_date") or "9999-12-31", task["task_id"]


def _complete_task_from_dashboard(storage, task: dict) -> None:
    storage.update_task_by_user(
        task["task_id"],
        title=task["title"],
        description=task.get("description"),
        due_date=task.get("due_date"),
        status="COMPLETED",
        reply_required=bool(task.get("reply_required")),
    )
    st.session_state["task_edit_flash"] = f"{task['title']} 업무를 완료했습니다."
    st.rerun()


def _go_to_operation_page(page: str) -> None:
    st.session_state["operation_page"] = page


def _operation_health_snapshot(storage, *, gmail_connected: bool) -> dict:
    operation_settings = storage.get_operation_settings()
    sync_runs = storage.list_sync_runs(source="GMAIL", limit=1)
    latest = sync_runs[0] if sync_runs else None
    enabled = bool(operation_settings["gmail_auto_sync_enabled"])
    if latest and latest["status"] in {"FAILED", "PARTIAL"}:
        tone = "danger"
    elif not enabled or not gmail_connected:
        tone = "warning"
    else:
        tone = "ok"
    if latest and latest.get("finished_at"):
        last_checked = datetime.fromisoformat(latest["finished_at"]).astimezone()
        last_checked_text = last_checked.strftime("%m-%d %H:%M")
    else:
        last_checked_text = "기록 없음"
    return {
        "tone": tone,
        "agent": (
            f"Agent 실행 중 · {operation_settings['gmail_sync_interval_minutes']}분 주기"
            if enabled
            else "Agent 일시정지"
        ),
        "gmail": "Gmail 연결됨" if gmail_connected else "Gmail 연결 필요",
        "last_checked": last_checked_text,
        "failed_count": int(latest["failed_count"]) if latest else 0,
        "latest": latest,
    }


@st.fragment(run_every="10s")
def _render_operation_status_bar(storage, *, gmail_connected: bool) -> None:
    health = _operation_health_snapshot(storage, gmail_connected=gmail_connected)
    st.markdown(
        f"""
        <div class="operation-status-bar {health['tone']}">
          <span><span class="status-dot"></span><strong>{health['agent']}</strong></span>
          <span class="status-separator">|</span>
          <span>{health['gmail']}</span>
          <span class="status-separator">|</span>
          <span>마지막 확인 {health['last_checked']}</span>
          <span class="status-separator">|</span>
          <span>최근 오류 <strong>{health['failed_count']}건</strong></span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_summary_cards(values: list[tuple[str, str, str]]) -> None:
    cards = "".join(
        f'<div class="work-summary-card {tone}">'
        f'<div class="work-summary-label">{label}</div>'
        f'<div class="work-summary-value">{value}</div></div>'
        for label, value, tone in values
    )
    st.markdown(f'<div class="work-summary-grid">{cards}</div>', unsafe_allow_html=True)


def _render_work_summary(priority_by_task: dict, active_tasks: list[dict], review_count: int) -> None:
    values = [
        (
            "즉시 처리",
            f"{sum(item.level == PriorityLevel.P1 for item in priority_by_task.values())}건",
            "red",
        ),
        (
            "우선 처리",
            f"{sum(item.level == PriorityLevel.P2 for item in priority_by_task.values())}건",
            "orange",
        ),
        (
            "회신 대기",
            f"{sum(task['status'] == 'WAITING_REPLY' for task in active_tasks)}건",
            "yellow",
        ),
        ("검토 요청", f"{review_count}건", "purple"),
    ]
    _render_summary_cards(values)


def _render_product_dashboard(
    storage,
    mails,
    *,
    operation_mode: bool = False,
    mail_source: str | None = None,
) -> None:
    tasks = storage.list_tasks()
    pending_reviews = storage.list_pending_reviews()
    total_mail_count = len(mails)
    processed_count = sum(storage.is_processed(mail.mail_id) for mail in mails)
    active_tasks = [
        task for task in tasks if task["status"] not in {"COMPLETED", "CANCELLED"}
    ]
    attention_tasks = [task for task in active_tasks if _task_attention(task) != "-"]
    priority_rules = storage.list_priority_rules()
    priority_settings = storage.get_priority_settings()
    priority_by_task = {
        task["task_id"]: calculate_task_priority(task, priority_rules, priority_settings)
        for task in active_tasks
    }

    if operation_mode:
        st.subheader("업무 홈")
        st.caption("오늘 처리할 업무와 사용자 확인이 필요한 항목을 한눈에 확인하세요.")
        _render_operation_status_bar(
            storage,
            gmail_connected=mail_source == GMAIL_TEST_SOURCE,
        )
        _render_work_summary(priority_by_task, active_tasks, len(pending_reviews))
        filtered_tasks = active_tasks
    else:
        st.subheader("오늘")
        st.caption("지금 처리할 업무와 확인이 필요한 결정을 우선순위대로 모았습니다.")
        summary_1, summary_2, summary_3, summary_4 = st.columns(4)
        summary_1.metric("처리된 Mail", f"{processed_count}/{total_mail_count}건")
        summary_2.metric("활성 업무", f"{len(active_tasks)}건")
        summary_3.metric("기한·대기 주의", f"{len(attention_tasks)}건")
        summary_4.metric("Agent 확인 필요", f"{len(pending_reviews)}건")
        search_text = st.text_input(
            "업무 검색",
            placeholder="업무 제목, 설명 또는 요청자를 검색하세요",
            key="dashboard_task_search",
        ).strip().casefold()
        filtered_tasks = active_tasks
        if search_text:
            filtered_tasks = [
                task
                for task in active_tasks
                if search_text
                in " ".join(
                    filter(
                        None,
                        [task.get("title"), task.get("description"), task.get("requester")],
                    )
                ).casefold()
            ]

    if operation_mode:
        prioritized = sorted(
            filtered_tasks,
            key=lambda task: _task_priority(task, priority_by_task[task["task_id"]].level),
        )
        if pending_reviews:
            review_col, review_action_col = st.columns([4.5, 1.2])
            review_col.warning(
                f"검토 요청 {len(pending_reviews)}건 · 자동 반영을 멈추고 사용자의 결정을 기다리고 있습니다."
            )
            review_action_col.button(
                "검토 요청 보기",
                width="stretch",
                on_click=_go_to_operation_page,
                args=(REVIEW_PAGE,),
            )

        st.markdown("### 우선순위 업무")
        st.caption(
            "🔴 즉시 처리(P1) · 🟠 우선 처리(P2) · "
            "🟡 회신 대기(업무 상태) · 🟣 검토 요청(사용자 결정 대기)"
        )
        st.caption(
            "목록은 기한·회신 대기의 긴급도와 VIP·고객사·키워드·사용자 지정 중요도를 "
            "함께 반영해 정렬합니다."
        )
        if not prioritized:
            st.info("진행 중인 업무가 없습니다. 새 업무 메일이 도착하면 자동으로 여기에 추가됩니다.")
        for task in prioritized[:5]:
            decision = priority_by_task[task["task_id"]]
            with st.container(border=True):
                mark_col, content_col, action_col = st.columns([0.4, 5.3, 1.25])
                mark_col.markdown(f"### {decision.emoji}")
                content_col.markdown(f"**{task['title']}**")
                content_col.caption(
                    f"{decision.label} · {STATUS_LABELS.get(task['status'], task['status'])} · "
                    f"기한 {task.get('due_date') or '없음'} · {task.get('requester') or '요청자 없음'}"
                )
                content_col.caption(f"우선순위 근거 · {decision.reason}")
                if action_col.button(
                    "완료 처리",
                    key=f"complete_today_{task['task_id']}",
                    width="stretch",
                ):
                    try:
                        _complete_task_from_dashboard(storage, task)
                    except ValueError as exc:
                        st.error(f"완료할 수 없습니다: {exc}")
        st.button(
            "전체 업무 보기",
            width="stretch",
            on_click=_go_to_operation_page,
            args=(TASKS_PAGE,),
            key="home_open_all_tasks",
        )

        st.divider()
        st.markdown("### 최근 변경")
        st.caption("최근 생성·수정·완료된 업무입니다. 상세 근거는 운영 상태에서 확인할 수 있습니다.")
        recent_histories = storage.list_histories()[:3]
        task_by_id = {task["task_id"]: task for task in tasks}
        if recent_histories:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "시각": datetime.fromisoformat(history["created_at"])
                            .astimezone()
                            .strftime("%m-%d %H:%M"),
                            "변경": ACTION_LABELS.get(history["action"], history["action"]),
                            "업무": task_by_id.get(history["task_id"], {}).get("title", "-")
                            if history["task_id"]
                            else "메일 처리",
                            "처리 방식": "사용자 확인" if history["user_decision"] else "자동",
                        }
                        for history in recent_histories
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("새 메일이 정리되면 최근 처리 결과가 여기에 표시됩니다.")

        st.markdown("### 최근 메일")
        if mail_source == GMAIL_TEST_SOURCE:
            st.caption(
                "마지막 Gmail 확인 결과 중 최근 3건입니다. 자동 정리 주기에 맞춰 갱신됩니다."
            )
            latest_mails = sorted(
                mails,
                key=lambda mail: mail.occurred_at,
                reverse=True,
            )[:3]
            if not latest_mails:
                st.info("연결된 Gmail 테스트 라벨에 표시할 메일이 없습니다.")
            for mail in latest_mails:
                stored = storage.get_processing_result(mail.mail_id)
                action = stored.get("proposal", {}).get("action") if stored else None
                status_text = ACTION_LABELS.get(action, action) if action else "새 메일"
                with st.container(border=True):
                    subject_col, status_col = st.columns([4.5, 1.4])
                    subject_col.markdown(f"**{mail.subject}**")
                    subject_col.caption(
                        f"{'🔵 받은 메일' if mail.direction.value == 'INBOUND' else '🟣 보낸 메일'} · "
                        f"{mail.sender} · {mail.occurred_at.astimezone().strftime('%m-%d %H:%M')}"
                    )
                    status_col.caption(status_text)
        else:
            st.info("Gmail을 연결하면 최근 메일 3건과 정리 결과가 여기에 표시됩니다.")
        return

    priority_col, attention_col = st.columns([1.7, 1])
    with priority_col:
        st.markdown("### 우선 처리 업무")
        prioritized = sorted(filtered_tasks, key=_task_priority)
        if prioritized:
            priority_frame = pd.DataFrame(
                [
                    {
                        "업무": task["title"],
                        "우선순위": priority_by_task[task["task_id"]].display,
                        "상태": STATUS_LABELS.get(task["status"], task["status"]),
                        "기한": task.get("due_date") or "없음",
                        "요청자": task.get("requester") or "-",
                        "주의": _task_attention(task),
                    }
                    for task in prioritized
                ]
            )
            st.dataframe(priority_frame, width="stretch", hide_index=True)
        elif search_text:
            st.info("검색 조건에 맞는 활성 업무가 없습니다.")
        else:
            st.info("메일을 처리하면 우선순위 업무가 여기에 표시됩니다.")

    with attention_col:
        st.markdown("### 오늘의 주의 항목")
        if pending_reviews:
            first_review = pending_reviews[0]
            st.warning(
                f"Agent 확인 필요 {len(pending_reviews)}건 · "
                f"{first_review['mail_id']} {first_review['proposal']['reason']}"
            )
        for task in sorted(attention_tasks, key=_task_priority)[:3]:
            with st.container(border=True):
                st.markdown(f"**{task['title']}**")
                st.caption(
                    f"{_task_attention(task)} · "
                    f"{STATUS_LABELS.get(task['status'], task['status'])} · "
                    f"{task.get('requester') or '요청자 없음'}"
                )
        if not pending_reviews and not attention_tasks:
            st.success("지금 확인이 필요한 변경이나 일정 경고가 없습니다.")

    st.divider()
    _render_tasks_and_histories(storage)


def _render_agent_result(result: dict) -> None:
    action = result["proposal"]["action"]
    st.subheader("처리 결과")
    if result.get("duplicate"):
        st.info("이미 처리된 mail_id입니다. 기존 결과만 반환했고 LLM과 DB를 재실행하지 않았습니다.")
    elif result["proposal"].get("needs_user_confirmation"):
        if action == AgentAction.MARK_COMPLETED.value:
            st.warning("완료 근거는 확인했지만 Task 상태는 바꾸지 않았습니다. ‘확인 필요’ 탭에서 승인해 주세요.")
        else:
            st.warning("판단이 애매해 자동 변경을 멈췄습니다. ‘확인 필요’ 탭에서 최종 결정해 주세요.")
    elif action == AgentAction.IGNORE.value:
        st.info("업무로 관리할 필요가 없는 메일이어서 Task는 변경하지 않았습니다.")
    else:
        st.success(f"Agent가 **{ACTION_LABELS.get(action, action)}** 처리를 완료했습니다.")
    c1, c2, c3 = st.columns(3)
    target_task = result["proposal"].get("target_task_id")
    if not target_task and result.get("task"):
        target_task = result["task"].get("task_id")
    c1.metric("Agent 결정", _action_label(action))
    c2.metric("신뢰도", f"{result['proposal']['confidence']:.0%}")
    c3.metric("대상 Task", target_task or "-")
    st.write("**왜 이렇게 판단했나요?**", result["proposal"]["reason"])

    candidates = result.get("candidate_tasks", [])
    if candidates:
        st.markdown("**관련 Task 후보**")
        st.dataframe(
            _candidate_frame(candidates),
            width="stretch",
            hide_index=True,
        )
    with st.expander("판단에 사용한 Mail·Task Context"):
        thread_history = result.get("thread_history", [])
        task_context = result.get("current_task_context")
        validation_result = result.get("validation_result", {})
        st.write(f"동일 Thread 선행 Mail: {len(thread_history)}건")
        if thread_history:
            st.dataframe(
                pd.DataFrame(thread_history)[
                    ["mail_id", "direction", "occurred_at", "subject"]
                ],
                width="stretch",
                hide_index=True,
            )
        if task_context:
            st.write(
                f"선택 Task: {task_context['task']['task_id']} · "
                f"최근 History {len(task_context.get('recent_histories', []))}건"
            )
        else:
            st.caption("단일 선택 Task Context 없음")
        st.json({"validation_result": validation_result})
    with st.expander("기술 상세 · 구조화된 Mail 분석"):
        st.json(result["analysis"])
    if result.get("before") or result.get("after"):
        before_col, after_col = st.columns(2)
        before_col.markdown("**변경 전**")
        before_col.json(result.get("before") or {})
        after_col.markdown("**변경 후**")
        after_col.json(result.get("after") or {})
    if result.get("review_result"):
        st.success(f"사용자 최종 결정: {result['review_result']['final_action']}")


def _run_demo(storage, settings, mail_by_id, scenario_key: str) -> None:
    scenario = DEMO_SCENARIOS[scenario_key]
    storage.reset()
    workflow = MailTaskWorkflow(settings, storage, build_analyzer(settings))
    results = []
    with st.spinner(f"{scenario['title']} 시나리오를 실행하고 있습니다..."):
        for mail_id in scenario["mail_ids"]:
            results.append(workflow.process(mail_by_id[mail_id]))
    st.session_state["last_result"] = results[-1].model_dump(mode="json")
    actions = [result.proposal.action.value for result in results]
    st.session_state["demo_flash"] = {
        "title": scenario["title"],
        "mail_ids": scenario["mail_ids"],
        "actions": actions,
    }
    st.rerun()


def _render_quick_demo(storage, settings, mail_by_id) -> None:
    st.subheader("한 번에 보는 자동 처리 시연")
    st.caption("각 시연은 결과가 섞이지 않도록 데모 DB를 초기화한 뒤 합성 메일을 순서대로 투입합니다.")
    columns = st.columns(len(DEMO_SCENARIOS))
    for column, (key, scenario) in zip(columns, DEMO_SCENARIOS.items()):
        with column:
            st.markdown(f"#### {scenario['title']}")
            st.write(scenario["description"])
            st.caption(" → ".join(scenario["mail_ids"]))
            if st.button("이 시나리오 실행", key=f"demo_{key}", width="stretch"):
                try:
                    _run_demo(storage, settings, mail_by_id, key)
                except Exception as exc:
                    st.error(f"시나리오 실행 실패: {type(exc).__name__}")
                    st.info("실행 로그 탭에서 어느 단계에서 중단됐는지 확인할 수 있습니다.")

    flash = st.session_state.get("demo_flash")
    if flash:
        action_text = " → ".join(ACTION_LABELS.get(action, action) for action in flash["actions"])
        st.success(f"{flash['title']} 완료: {action_text}")
        if AgentAction.ASK_USER.value in flash["actions"]:
            st.info("마지막 단계는 의도적으로 멈춰 있습니다. ‘확인 필요’ 탭에서 사용자가 결정합니다.")
        result = st.session_state.get("last_result")
        if result:
            _render_agent_result(result)


def _render_mail_preview(mail) -> None:
    occurred_at = mail.occurred_at.strftime("%Y-%m-%d %H:%M")
    st.markdown(
        f"""
        <div class="mail-card">
          <small>{mail.mail_id} · {mail.direction.value} · {occurred_at}</small><br/>
          <strong>{mail.subject}</strong><br/>
          <small>보낸 사람: {mail.sender}</small><br/><br/>
          {mail.body}
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("기술 상세 · 원본 JSON"):
        st.json(mail.model_dump(mode="json"))


def _mail_overview(mails, storage) -> pd.DataFrame:
    stored_results = {
        item["mail_id"]: item for item in storage.list_processing_results()
    }
    failed_events = {}
    for event in storage.list_events():
        if event["step"] == "PROCESS_FAILED" and event["mail_id"] not in failed_events:
            failed_events[event["mail_id"]] = event
    rows = []
    for mail in mails:
        stored = stored_results.get(mail.mail_id)
        result = stored["result"] if stored else None
        proposal = result.get("proposal", {}) if result else {}
        analysis = result.get("analysis", {}) if result else {}
        review = result.get("review_result") if result else None
        if not result and mail.mail_id in failed_events:
            processing_status = "실패 · 재처리 가능"
            action = "-"
        elif not result:
            processing_status = "미처리"
            action = "-"
        elif proposal.get("needs_user_confirmation") and not review:
            processing_status = "사용자 확인 필요"
            action = proposal.get("action", "-")
        elif review:
            processing_status = "사용자 결정 완료"
            action = review.get("final_action", proposal.get("action", "-"))
        else:
            processing_status = "자동 처리 완료"
            action = proposal.get("action", "-")
        task_id = None
        if result:
            task_id = result.get("task_id") or proposal.get("target_task_id")
        rows.append(
            {
                "Mail ID": mail.mail_id,
                "수신·발신": "수신" if mail.direction.value == "INBOUND" else "발신",
                "시각": mail.occurred_at.strftime("%m-%d %H:%M"),
                "제목": mail.subject,
                "분류": INTENT_LABELS.get(analysis.get("intent"), "미분류"),
                "처리 상태": processing_status,
                "Agent Action": ACTION_LABELS.get(action, action),
                "Task": task_id or "-",
            }
        )
    return pd.DataFrame(rows)


def _run_unprocessed_mail_batch(
    storage,
    settings,
    mails,
    *,
    on_progress=None,
) -> dict:
    pending_mails = [mail for mail in mails if not storage.is_processed(mail.mail_id)]
    workflow = (
        MailTaskWorkflow(settings, storage, build_operational_analyzer(settings, storage))
        if pending_mails
        else None
    )
    succeeded = 0
    failed = []
    last_result = None
    for index, mail in enumerate(pending_mails, start=1):
        if on_progress:
            on_progress(index, len(pending_mails), mail)
        try:
            last_result = workflow.process(mail)
            succeeded += 1
        except Exception as exc:
            failed.append({"mail_id": mail.mail_id, "error": type(exc).__name__})
    return {
        "pending_count": len(pending_mails),
        "success": succeeded,
        "failed": failed,
        "last_result": last_result,
    }


def _process_unprocessed_mails(
    storage,
    settings,
    mails,
    source_batch_name: str = "합성 메일",
) -> None:
    progress = st.progress(0, text="메일 자동 정리를 시작합니다.")

    def update_progress(index, total, mail) -> None:
        progress.progress(
            index / total,
            text=f"{mail.mail_id} · {mail.subject}",
        )

    batch = _run_unprocessed_mail_batch(
        storage,
        settings,
        mails,
        on_progress=update_progress,
    )
    if not batch["pending_count"]:
        st.session_state["batch_flash"] = {
            "success": 0,
            "failed": [],
            "message": f"모든 {source_batch_name}이 이미 처리됐습니다.",
        }
        st.rerun()

    last_result = batch["last_result"]
    if last_result:
        st.session_state["last_result"] = last_result.model_dump(mode="json")
    st.session_state["batch_flash"] = {
        "success": batch["success"],
        "failed": batch["failed"],
        "message": (
            f"미처리 {source_batch_name} {batch['pending_count']}건 자동 정리를 실행했습니다."
        ),
    }
    st.rerun()


def _render_mailbox(
    storage,
    settings,
    mails,
    source_name: str,
    demo_mode: bool = True,
) -> None:
    st.subheader("메일 처리함")
    if source_name == GMAIL_TEST_SOURCE:
        st.caption(
            "OAuth 읽기 전용으로 제한된 Gmail 테스트 라벨의 메일만 가져옵니다. "
            "메일 작성·전송·삭제 권한은 없으며 전체 받은편지함을 자동 처리하지 않습니다."
        )
    else:
        st.caption(
            "연결된 입력 Source에서 들어온 메일의 분류와 처리 결과를 한곳에서 봅니다. "
            "현재 Source는 합성 Dataset이며, 실제 Outlook 전체 메일함을 읽는 단계는 아닙니다."
        )

    batch_flash = st.session_state.pop("batch_flash", None)
    if batch_flash:
        if batch_flash["failed"]:
            st.warning(
                f"{batch_flash['message']} 성공 {batch_flash['success']}건, "
                f"실패 {len(batch_flash['failed'])}건"
            )
            with st.expander("실패 메일 확인"):
                st.json(batch_flash["failed"])
        else:
            st.success(f"{batch_flash['message']} 성공 {batch_flash['success']}건")

    if not mails:
        st.info(
            "현재 입력 Source에서 가져온 메일이 없습니다. Gmail 테스트라면 "
            "`MailTaskAgent-Demo` 라벨을 붙인 합성 테스트 메일을 준비한 뒤 "
            "자동 정리를 켜 두세요. 연결 진단과 최근 실행 결과는 ‘운영 상태’에서 확인할 수 있습니다."
        )
        return

    overview = _mail_overview(mails, storage)
    status_options = list(overview["처리 상태"].drop_duplicates())
    selected_statuses = st.multiselect(
        "처리 상태 필터",
        status_options,
        default=status_options,
        key="mail_status_filter",
    )
    st.dataframe(
        overview[overview["처리 상태"].isin(selected_statuses)],
        width="stretch",
        hide_index=True,
    )

    unprocessed_count = sum(not storage.is_processed(mail.mail_id) for mail in mails)
    source_batch_name = (
        "Gmail 테스트 메일" if source_name == GMAIL_TEST_SOURCE else "합성 메일"
    )
    button_label = (
        f"미처리·실패 {source_batch_name} 전체 자동 정리 · {unprocessed_count}건"
        if demo_mode
        else f"미처리 메일 전체 분류 · {unprocessed_count}건"
    )
    if st.button(
        button_label,
        type="primary",
        disabled=unprocessed_count == 0,
        width="stretch",
    ):
        _process_unprocessed_mails(
            storage,
            settings,
            mails,
            source_batch_name=source_batch_name,
        )

    if demo_mode:
        with st.expander("메일 한 건 직접 처리"):
            selected = st.selectbox(
                "어떤 메일이 도착했다고 가정할까요?",
                mails,
                format_func=_friendly_mail,
            )
            _render_mail_preview(selected)
            selected_failed = any(
                event["step"] == "PROCESS_FAILED"
                for event in storage.list_events(selected.mail_id)
            ) and not storage.is_processed(selected.mail_id)
            selected_button_label = (
                "선택한 메일 재처리" if selected_failed else "선택한 메일 처리"
            )
            if st.button(selected_button_label, width="stretch"):
                try:
                    workflow = MailTaskWorkflow(
                        settings,
                        storage,
                        build_operational_analyzer(settings, storage),
                    )
                    with st.spinner("Mail Context와 현재 Task State를 분석하고 있습니다..."):
                        result = workflow.process(selected)
                    st.session_state["last_result"] = result.model_dump(mode="json")
                    st.rerun()
                except Exception as exc:
                    st.error(f"처리 실패: {type(exc).__name__}")
                    st.info("운영 로그에 실패 단계가 남고 Task 변경은 수행되지 않습니다.")

    result = st.session_state.get("last_result")
    if result:
        _render_agent_result(result)


def _render_review_queue(storage, settings, mail_by_id) -> None:
    pending = storage.list_pending_reviews()
    st.subheader("사용자 확인 대기")
    if not pending:
        st.info("현재 ASK_USER 확인 대기 항목이 없습니다.")
        return

    selected_review = st.selectbox(
        "확인할 Mail",
        pending,
        format_func=lambda item: f"{item['mail_id']} · {item['proposal']['reason']}",
        key="pending_review_selector",
    )
    mail_id = selected_review["mail_id"]
    source_mail = mail_by_id.get(mail_id)
    if source_mail is None:
        st.warning(
            "원본 Mail이 현재 입력 Source에 없습니다. Gmail Mail이라면 사이드바에서 "
            "Gmail 테스트를 선택해 다시 불러온 뒤 사용자 결정을 진행하세요."
        )
        return
    candidates = selected_review.get("candidate_tasks", [])
    proposal_action = selected_review["proposal"]["action"]
    proposed_status = selected_review["proposal"].get("changes", {}).get("status")
    is_cancellation_review = proposed_status == "CANCELLED"
    proposed_due_date = selected_review["proposal"].get("changes", {}).get("due_date")
    is_due_date_review = bool(proposed_due_date)
    st.warning(
        f"Agent가 자동 변경을 중단했습니다: "
        f"{_action_label(proposal_action)} · {selected_review['proposal']['reason']}"
    )
    if candidates:
        st.dataframe(
            _candidate_frame(candidates),
            width="stretch",
            hide_index=True,
        )

    labels = {}
    if proposal_action == AgentAction.MARK_COMPLETED.value:
        labels["완료 승인"] = ReviewDecision.APPROVE_PROPOSAL
        labels["완료하지 않음"] = ReviewDecision.IGNORE
    elif is_cancellation_review:
        labels["취소 승인"] = ReviewDecision.APPROVE_PROPOSAL
        labels["취소하지 않음"] = ReviewDecision.IGNORE
    elif is_due_date_review:
        labels["기한 변경 승인"] = ReviewDecision.APPROVE_PROPOSAL
        labels["기존 기한 유지"] = ReviewDecision.IGNORE
    else:
        if candidates:
            can_resume_waiting = (
                source_mail.direction == MailDirection.INBOUND
                and any(
                    candidate.get("status") == "WAITING_REPLY"
                    for candidate in candidates
                )
            )
            if can_resume_waiting:
                labels["기존 Task 연결 및 진행 재개"] = ReviewDecision.LINK_EXISTING
                labels["기존 Task에 연결만"] = ReviewDecision.LINK_EXISTING
            else:
                labels["기존 Task 연결"] = ReviewDecision.LINK_EXISTING
        labels["신규 Task 생성"] = ReviewDecision.CREATE_NEW
        labels["무시"] = ReviewDecision.IGNORE
    choice_label = st.radio("사용자 최종 결정", list(labels), horizontal=True)
    decision = labels[choice_label]

    target_task_id = None
    new_task_title = None
    approved_changes = None
    if decision == ReviewDecision.LINK_EXISTING:
        selected_candidate = st.selectbox(
            "연결할 Task",
            candidates,
            format_func=lambda item: f"{item['task_id']} · {item['title']}",
        )
        target_task_id = selected_candidate["task_id"]
        if choice_label == "기존 Task 연결 및 진행 재개":
            approved_changes = {
                "status": "IN_PROGRESS",
                "waiting_since": None,
            }
    elif decision == ReviewDecision.CREATE_NEW:
        default_title = (
            selected_review["analysis"].get("task_title")
            or selected_review["analysis"].get("request_summary")
            or source_mail.subject
        )
        new_task_title = st.text_input("새 Task 제목", value=default_title)

    if proposal_action == AgentAction.MARK_COMPLETED.value:
        target_task_id = selected_review["proposal"].get("target_task_id")
        st.caption(f"대상 Task: {target_task_id} · 승인 전에는 현재 상태를 유지합니다.")
    elif is_cancellation_review:
        target_task_id = selected_review["proposal"].get("target_task_id")
        st.caption(f"대상 Task: {target_task_id} · 승인 전에는 취소하지 않습니다.")
    elif is_due_date_review:
        target_task_id = selected_review["proposal"].get("target_task_id")
        approved_due_date = st.date_input(
            "확정할 기한",
            value=date.fromisoformat(proposed_due_date),
            help="Agent 제안 날짜를 그대로 승인하거나 사용자가 날짜를 수정할 수 있습니다.",
        )
        approved_changes = {"due_date": approved_due_date.isoformat()}
        st.caption(f"대상 Task: {target_task_id} · 사용자 확정 전에는 기존 기한을 유지합니다.")

    if st.button("사용자 결정 확정", type="primary"):
        try:
            workflow = MailTaskWorkflow(settings, storage, build_analyzer(settings))
            review_result = workflow.resolve_review(
                mail=source_mail,
                decision=decision,
                target_task_id=target_task_id,
                new_task_title=new_task_title,
                approved_changes=approved_changes,
            )
            st.session_state["review_flash"] = (
                f"{mail_id}: {review_result['final_action']} 반영 및 History 저장 완료"
            )
            st.session_state.pop("last_result", None)
            st.rerun()
        except Exception as exc:
            st.error(f"사용자 결정 반영 실패: {type(exc).__name__}")


def _agentic_trace_phase(step: str) -> tuple[str, str]:
    if step in {"MAIL_INPUT", "SCHEMA_VALIDATION", "M-01 LLM_ANALYSIS"}:
        return "Observe Input / Analyze", "👁️"
    if step == "M-02 CONTEXT_ROUTE":
        return "Reason / Plan", "🧠"
    if step in {
        "M-02 TASK_MATCHING",
        "M-02 RAG_RETRIEVAL",
        "M-02 RAG_RETRIEVAL_RETRY",
    }:
        return "Act / Retrieve", "🔍"
    if step in {"M-02 CONTEXT_OBSERVATION", "M-02 CONTEXT_REOBSERVATION"}:
        return "Observe Context", "👀"
    if step in {"M-03 RAG_DECISION", "M-03 RAG_REDECISION"}:
        return "Re-evaluate / Decide", "🧠"
    if step == "M-03 QUERY_REWRITE":
        return "Reason / Re-plan", "🔁"
    if step == "M-03 AGENT_ACTION_PROPOSAL":
        return "Agent Action Proposal", "🤖"
    if step in {"M-03 PYTHON_GUARD", "M-03 ACTION_DECISION", "ACTION_VALIDATION"}:
        return "Python Guard", "🛡️"
    if step == "M-04 DB_TRANSACTION":
        return "Act / Execute", "🛠️"
    if step in {"ASK_USER", "RAG_FALLBACK"}:
        return "Guard / Handoff", "🙋"
    if step == "M-04 EXECUTION_OBSERVATION":
        return "Observe Result", "🔎"
    if step in {"PROCESS_COMPLETED", "FINAL_OUTPUT"}:
        return "Final Output", "✅"
    return "Workflow Event", "•"


def _render_agentic_trace(events: list[dict], mail_ids: list[str]) -> None:
    st.markdown("### Agentic Workflow Trace")
    st.caption(
        "Agent가 입력을 관찰하고 Context를 검색한 뒤 판단·행동·결과 관찰·최종 출력을 "
        "수행한 과정을 보여줍니다. 원시 사고과정 대신 검증 가능한 근거만 표시합니다."
    )
    ordered_mail_ids = list(
        dict.fromkeys(event["mail_id"] for event in sorted(events, key=lambda item: item["event_id"], reverse=True))
    )
    for mail_id in mail_ids:
        if mail_id not in ordered_mail_ids:
            ordered_mail_ids.append(mail_id)
    trace_mail_id = st.selectbox(
        "Trace를 확인할 Mail",
        ordered_mail_ids,
        key="agentic_trace_mail_id",
    )
    trace_events = sorted(
        [event for event in events if event["mail_id"] == trace_mail_id],
        key=lambda item: item["event_id"],
    )
    if not trace_events:
        st.info("선택한 Mail의 Agent 실행 기록이 없습니다.")
        return

    for event in trace_events:
        phase, icon = _agentic_trace_phase(event["step"])
        details = _parse_json(event["details_json"])
        with st.container(border=True):
            phase_col, step_col, result_col = st.columns([1.3, 2.4, 0.9])
            phase_col.markdown(f"**{icon} {phase}**")
            step_col.markdown(f"**{event['step']}**")
            result_col.markdown(
                "🟢 성공"
                if event["status"] == "SUCCESS"
                else "🟡 대기"
                if event["status"] in {"WAITING", "STARTED"}
                else "🔴 실패"
            )
            st.write(event["message"])
            if isinstance(details, dict):
                summary_parts = []
                for key, label in (
                    ("route", "경로"),
                    ("relation", "관계"),
                    ("agent_action", "Agent 제안"),
                    ("verdict", "Guard"),
                    ("action", "Action"),
                    ("final_action", "최종 Action"),
                    ("selected_task_id", "선택 Task"),
                    ("confidence", "신뢰도"),
                    ("retry_count", "재시도"),
                ):
                    value = details.get(key)
                    if value is not None:
                        summary_parts.append(f"**{label}** {value}")
                if summary_parts:
                    st.caption(" · ".join(summary_parts))
                retrieval_results = details.get("retrieval_results")
                if isinstance(retrieval_results, list) and retrieval_results:
                    st.dataframe(
                        pd.DataFrame(retrieval_results),
                        width="stretch",
                        hide_index=True,
                    )
                observed_contexts = details.get("observed_contexts")
                if isinstance(observed_contexts, list) and observed_contexts:
                    st.dataframe(
                        pd.DataFrame(observed_contexts),
                        width="stretch",
                        hide_index=True,
                    )
                decision_reason = details.get("reason") or details.get("decision_reason")
                if decision_reason:
                    st.caption(f"판단 근거: {decision_reason}")
            st.caption(
                f"{event['created_at']}"
                + (
                    f" · {int(event['duration_ms'])} ms"
                    if event["duration_ms"] is not None
                    else ""
                )
            )


def _render_event_log(storage, mail_ids: list[str]) -> None:
    st.subheader("Agent 실행 로그")
    st.caption("M-01~M-05 처리 단계, 성공·실패, 소요 시간과 정제된 상세 정보를 표시합니다.")
    events = storage.list_events()
    if not events:
        st.info("아직 실행 로그가 없습니다.")
        return

    _render_agentic_trace(events, mail_ids)
    st.divider()
    st.markdown("### 전체 기술 로그")

    known_mail_ids = sorted({*mail_ids, *(event["mail_id"] for event in events)})
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    mail_filter = filter_col1.selectbox(
        "Mail ID", ["전체", *known_mail_ids], key="log_mail_filter"
    )
    levels = sorted({event["level"] for event in events})
    level_filter = filter_col2.selectbox("Level", ["전체", *levels], key="log_level_filter")
    steps = sorted({event["step"] for event in events})
    step_filter = filter_col3.selectbox("처리 단계", ["전체", *steps], key="log_step_filter")

    filtered = [
        event
        for event in events
        if (mail_filter == "전체" or event["mail_id"] == mail_filter)
        and (level_filter == "전체" or event["level"] == level_filter)
        and (step_filter == "전체" or event["step"] == step_filter)
    ]
    display = pd.DataFrame(filtered)
    if display.empty:
        st.warning("선택한 조건의 로그가 없습니다.")
        return
    display["duration_ms"] = display["duration_ms"].apply(
        lambda value: "-" if pd.isna(value) else str(int(value))
    )
    st.dataframe(
        display[
            [
                "event_id",
                "created_at",
                "mail_id",
                "step",
                "status",
                "level",
                "duration_ms",
                "message",
            ]
        ],
        width="stretch",
        hide_index=True,
    )
    selected_event = st.selectbox(
        "상세 로그",
        filtered,
        format_func=lambda item: (
            f"#{item['event_id']} · {item['mail_id']} · {item['step']} · {item['status']}"
        ),
    )
    details = _parse_json(selected_event["details_json"])
    st.markdown("#### 선택 로그 요약")
    with st.container(border=True):
        step_col, status_col, duration_col = st.columns(3)
        step_col.metric("처리 단계", selected_event["step"])
        status_col.metric("결과", selected_event["status"])
        duration_col.metric(
            "소요 시간",
            (
                f"{int(selected_event['duration_ms'])} ms"
                if selected_event["duration_ms"] is not None
                else "-"
            ),
        )
        if selected_event["status"] == "SUCCESS":
            st.success(selected_event["message"])
        elif selected_event["level"] == "ERROR":
            st.error(selected_event["message"])
        else:
            st.warning(selected_event["message"])
        st.caption(
            f"Mail {selected_event['mail_id']} · Case {selected_event['case_id']} · "
            f"{selected_event['created_at']}"
        )
        detail_rows = _detail_rows(details)
        if detail_rows:
            st.dataframe(pd.DataFrame(detail_rows), width="stretch", hide_index=True)
        else:
            st.caption("이 단계에는 별도 상세 데이터가 없습니다.")
    with st.expander("Audit 원문 · 정제된 기술 데이터"):
        st.json(
            {
                "case_id": selected_event["case_id"],
                "message": selected_event["message"],
                "details": details,
                "duration_ms": selected_event["duration_ms"],
                "created_at": selected_event["created_at"],
            }
        )
    st.caption("API Key, Authorization Header, Token과 Secret 값은 저장 전에 제거됩니다.")


def _render_tasks_and_histories(storage, *, show_history: bool = True) -> None:
    st.subheader("내 업무")
    with st.expander("새 업무 직접 추가"):
        with st.form("manual_task_create_form"):
            new_title = st.text_input("업무 제목", placeholder="처리할 업무를 입력하세요")
            new_description = st.text_area("업무 설명", placeholder="필요한 내용만 간단히 입력하세요")
            new_status = st.selectbox(
                "시작 상태",
                ["TODO", "IN_PROGRESS", "WAITING_REPLY"],
                format_func=lambda value: STATUS_LABELS[value],
            )
            has_due_date = st.checkbox("기한 설정")
            new_due_date = st.date_input(
                "기한",
                value=date.today(),
                disabled=not has_due_date,
            )
            new_importance = st.selectbox(
                "중요도",
                [None, 1, 2, 3, 4],
                format_func=lambda value: (
                    "자동 계산"
                    if value is None
                    else f"{PRIORITY_PRESENTATION[PriorityLevel(f'P{value}')][0]} P{value}"
                ),
            )
            create_task = st.form_submit_button("업무 추가", type="primary")
        if create_task:
            try:
                created_task = storage.create_task_by_user(
                    title=new_title,
                    description=new_description,
                    due_date=new_due_date.isoformat() if has_due_date else None,
                    status=new_status,
                    importance=new_importance,
                )
                st.session_state["task_edit_flash"] = (
                    f"{created_task['title']} 업무를 추가하고 History에 기록했습니다."
                )
                st.rerun()
            except ValueError as exc:
                st.error(f"업무를 추가할 수 없습니다: {exc}")

    if not show_history:
        _render_operational_task_list(storage)
        return

    task_col, history_col = st.columns([1, 1.35])
    with task_col:
        tasks = storage.list_tasks()
        if tasks:
            priority_rules = storage.list_priority_rules()
            priority_settings = storage.get_priority_settings()
            priority_by_task = {
                task["task_id"]: calculate_task_priority(
                    task, priority_rules, priority_settings
                )
                for task in tasks
            }
            task_frame = pd.DataFrame(tasks)
            task_frame["상태"] = task_frame["status"].map(STATUS_LABELS).fillna(task_frame["status"])
            task_frame["주의"] = [_task_attention(task) for task in tasks]
            task_frame["우선순위"] = [
                priority_by_task[task["task_id"]].display for task in tasks
            ]
            attention_count = int((task_frame["주의"] != "-").sum())
            if attention_count:
                st.warning(f"확인이 필요한 일정 또는 대기 업무가 {attention_count}건 있습니다.")
            status_options = [status for status in STATUS_LABELS if status in set(task_frame["status"])]
            selected_statuses = st.multiselect(
                "상태 필터",
                status_options,
                default=status_options,
                format_func=lambda status: STATUS_LABELS[status],
            )
            task_frame = task_frame[task_frame["status"].isin(selected_statuses)]
            task_frame = task_frame.rename(
                columns={
                    "task_id": "Task ID",
                    "title": "업무 제목",
                    "due_date": "기한",
                    "waiting_since": "대기 시작",
                    "requester": "요청자",
                }
            )
            columns = [
                "우선순위",
                "업무 제목",
                "상태",
                "주의",
                "기한",
                "요청자",
                "Task ID",
            ]
            st.dataframe(task_frame[columns], width="stretch", hide_index=True)
            with st.expander("업무 상세 · 수정 · 완료"):
                selected_task = st.selectbox(
                    "수정할 Task",
                    tasks,
                    format_func=lambda item: f"{item['task_id']} · {item['title']}",
                    key="manual_task_selection",
                )
                current_due = (
                    date.fromisoformat(selected_task["due_date"])
                    if selected_task.get("due_date")
                    else date.today()
                )
                with st.form("manual_task_edit_form"):
                    edited_title = st.text_input("업무 제목", value=selected_task["title"])
                    edited_description = st.text_area(
                        "업무 설명", value=selected_task.get("description") or ""
                    )
                    edited_status = st.selectbox(
                        "상태",
                        list(STATUS_LABELS),
                        index=list(STATUS_LABELS).index(selected_task["status"]),
                        format_func=lambda value: STATUS_LABELS[value],
                    )
                    edited_due = st.date_input("기한", value=current_due)
                    no_due = st.checkbox(
                        "기한 없음", value=not bool(selected_task.get("due_date"))
                    )
                    edited_reply_required = st.checkbox(
                        "회신 필요", value=bool(selected_task.get("reply_required"))
                    )
                    importance_options = [None, 1, 2, 3, 4]
                    edited_importance = st.selectbox(
                        "중요도",
                        importance_options,
                        index=importance_options.index(
                            selected_task.get("importance_override")
                        ),
                        format_func=lambda value: (
                            "자동 계산"
                            if value is None
                            else f"{PRIORITY_PRESENTATION[PriorityLevel(f'P{value}')][0]} P{value}"
                        ),
                    )
                    current_priority = priority_by_task[selected_task["task_id"]]
                    st.caption(
                        f"현재 {current_priority.display} · {current_priority.reason}"
                    )
                    save_task = st.form_submit_button("변경 내용 저장", type="primary")
                if save_task:
                    try:
                        result = storage.update_task_by_user(
                            selected_task["task_id"],
                            title=edited_title,
                            description=edited_description,
                            due_date=None if no_due else edited_due.isoformat(),
                            status=edited_status,
                            reply_required=edited_reply_required,
                        )
                        if edited_importance != selected_task.get("importance_override"):
                            storage.set_task_importance(
                                selected_task["task_id"], edited_importance
                            )
                        st.session_state["task_edit_flash"] = (
                            f"{result['task_id']} 변경을 저장하고 History에 기록했습니다."
                        )
                        st.rerun()
                    except ValueError as exc:
                        st.error(f"변경할 수 없는 상태 또는 입력입니다: {exc}")
        else:
            st.info("아직 생성된 Task가 없습니다.")

    with history_col:
        st.subheader("Task History")
        histories = storage.list_histories()
        if not histories:
            st.info("아직 처리 History가 없습니다.")
            return
        display = pd.DataFrame(histories)
        st.dataframe(
            display[
                [
                    "created_at",
                    "mail_id",
                    "task_id",
                    "action",
                    "reason",
                    "confidence",
                    "user_decision",
                ]
            ],
            width="stretch",
            hide_index=True,
        )
        selected_history = st.selectbox(
            "History 상세",
            histories,
            format_func=lambda item: (
                f"#{item['history_id']} · {item['mail_id']} · {item['action']}"
            ),
        )
        before = _parse_json(selected_history["before_json"])
        after = _parse_json(selected_history["after_json"])
        user_decision = _parse_json(selected_history["user_decision"])
        change_rows = _history_change_rows(before, after)
        st.markdown("#### 선택 History 요약")
        with st.container(border=True):
            action_col, task_col, confidence_col = st.columns(3)
            action_col.metric(
                "Agent Action",
                ACTION_LABELS.get(selected_history["action"], selected_history["action"]),
            )
            task_col.metric("대상 Task", selected_history["task_id"] or "-")
            confidence_col.metric("신뢰도", f"{selected_history['confidence']:.0%}")
            st.caption(
                f"{selected_history['created_at']} · Source Mail {selected_history['mail_id']}"
            )
            st.info(f"판단 근거 · {selected_history['reason']}")
            if user_decision:
                st.success(f"사용자 최종 결정 · {_display_value(user_decision)}")
            else:
                st.caption("사용자 확인 없이 검증된 Agent Action이 반영되었습니다.")
            if change_rows:
                st.dataframe(pd.DataFrame(change_rows), width="stretch", hide_index=True)
            else:
                st.caption("Task 필드 변경 없이 Mail 연결 또는 처리 기록만 저장되었습니다.")
        with st.expander("Audit 원문 · 변경 전후 전체 데이터"):
            st.json(
                {
                    "처리 시각": selected_history["created_at"],
                    "Source Mail ID": selected_history["mail_id"],
                    "Action": selected_history["action"],
                    "변경 전": before,
                    "변경 후": after,
                    "Agent 판단 근거": selected_history["reason"],
                    "사용자 결정": user_decision,
                }
            )


def _clear_selected_operational_task() -> None:
    st.session_state.pop("selected_operational_task_id", None)


@st.dialog(
    "업무 상세",
    width="large",
    on_dismiss=_clear_selected_operational_task,
)
def _render_operational_task_detail(storage, selected_task: dict) -> None:
    st.caption("업무 상태·기한·중요도를 직접 수정하면 변경 기록이 자동으로 남습니다.")
    timeline_rows = _task_mail_timeline_rows(storage, selected_task)
    st.markdown("#### 메일 진행 타임라인")
    st.caption(
        "이 업무와 연결된 받은 메일과 보낸 회신을 시간순으로 보여줍니다. "
        "같은 Gmail 스레드의 후속 메일은 자동으로 이어집니다."
    )
    if not timeline_rows:
        st.info("이 업무에 연결된 메일 기록이 없습니다. 직접 추가한 업무일 수 있습니다.")
    else:
        for row in timeline_rows:
            with st.container(border=True):
                time_col, content_col, result_col = st.columns([1.35, 4.6, 1.7])
                occurred_at = datetime.fromisoformat(row["occurred_at"]).astimezone()
                time_col.markdown(f"**{row['direction_label']}**")
                time_col.caption(occurred_at.strftime("%m-%d %H:%M"))
                content_col.markdown(f"**{row['subject']}**")
                arrow = "보낸 사람" if row["direction"] == "INBOUND" else "받는 사람"
                content_col.caption(f"{arrow} · {row['counterpart']}")
                result_col.markdown(f"**{row['action_label']}**")
                if row["status"]:
                    result_col.caption(
                        f"상태 · {STATUS_LABELS.get(row['status'], row['status'])}"
                    )
    st.markdown("#### 업무 변경 기록")
    st.caption(
        "Agent의 자동 판단과 사용자 결정으로 이 업무가 어떻게 바뀌었는지 최신순으로 보여줍니다."
    )
    task_history_rows = _task_history_rows(storage, selected_task["task_id"])
    if task_history_rows:
        for row in task_history_rows[:5]:
            with st.container(border=True):
                action_col, source_col, decision_col = st.columns([1.5, 2.4, 1.5])
                action_col.markdown(f"**{row['Action']}**")
                source_col.caption(f"{row['처리 시각']} · {row['Source Mail']}")
                decision_col.markdown(f"**{row['사용자 결정']}**")
                st.caption(f"판단 근거 · {row['판단 근거']}")
                if row["변경 전"] == "-":
                    st.caption(row["변경 후"])
                else:
                    before_col, after_col = st.columns(2)
                    before_col.caption(f"변경 전 · {row['변경 전']}")
                    after_col.caption(f"변경 후 · {row['변경 후']}")
        if len(task_history_rows) > 5:
            with st.expander(f"이전 변경 기록 {len(task_history_rows) - 5}건"):
                st.dataframe(
                    pd.DataFrame(task_history_rows[5:]),
                    width="stretch",
                    hide_index=True,
                )
    else:
        st.info("아직 이 업무의 변경 기록이 없습니다.")
    current_due = (
        date.fromisoformat(selected_task["due_date"])
        if selected_task.get("due_date")
        else date.today()
    )
    importance_options = [None, 1, 2, 3, 4]
    with st.form("operational_task_edit_form"):
        edited_title = st.text_input("업무 제목", value=selected_task["title"])
        edited_description = st.text_area(
            "업무 설명",
            value=selected_task.get("description") or "",
        )
        status_input_col, due_input_col = st.columns(2)
        edited_status = status_input_col.selectbox(
            "상태",
            list(STATUS_LABELS),
            index=list(STATUS_LABELS).index(selected_task["status"]),
            format_func=lambda value: STATUS_LABELS[value],
        )
        edited_due = due_input_col.date_input("기한", value=current_due)
        no_due = st.checkbox("기한 없음", value=not bool(selected_task.get("due_date")))
        edited_reply_required = st.checkbox(
            "회신 필요",
            value=bool(selected_task.get("reply_required")),
        )
        edited_importance = st.selectbox(
            "중요도",
            importance_options,
            index=importance_options.index(selected_task.get("importance_override")),
            format_func=lambda value: (
                "자동 계산"
                if value is None
                else f"{PRIORITY_PRESENTATION[PriorityLevel(f'P{value}')][0]} P{value}"
            ),
        )
        save_task = st.form_submit_button("변경 내용 저장", type="primary")
    if save_task:
        try:
            result = storage.update_task_by_user(
                selected_task["task_id"],
                title=edited_title,
                description=edited_description,
                due_date=None if no_due else edited_due.isoformat(),
                status=edited_status,
                reply_required=edited_reply_required,
            )
            if edited_importance != selected_task.get("importance_override"):
                storage.set_task_importance(selected_task["task_id"], edited_importance)
            st.session_state["task_edit_flash"] = f"{result['title']} 변경을 저장했습니다."
            st.session_state.pop("selected_operational_task_id", None)
            st.rerun()
        except ValueError as exc:
            st.error(f"변경할 수 없는 상태 또는 입력입니다: {exc}")


def _render_operational_task_list(storage) -> None:
    tasks = storage.list_tasks()
    if not tasks:
        st.info("아직 등록된 업무가 없습니다. 메일에서 업무가 확인되면 자동으로 추가됩니다.")
        return

    priority_rules = storage.list_priority_rules()
    priority_settings = storage.get_priority_settings()
    priority_by_task = {
        task["task_id"]: calculate_task_priority(task, priority_rules, priority_settings)
        for task in tasks
    }
    search_col, status_col = st.columns([1.4, 1])
    search_text = search_col.text_input(
        "업무 검색",
        placeholder="제목, 설명 또는 요청자",
        key="operational_task_search",
    ).strip().casefold()
    selected_status = status_col.selectbox(
        "상태",
        ["ACTIVE", "ALL", *STATUS_LABELS],
        format_func=lambda status: {
            "ACTIVE": "진행 중인 업무",
            "ALL": "모든 업무",
        }.get(status, STATUS_LABELS.get(status, status)),
        key="operational_task_status_filter",
    )
    filtered_tasks = [
        task
        for task in tasks
        if (
            selected_status == "ALL"
            or selected_status == "ACTIVE"
            and task["status"] in {"TODO", "IN_PROGRESS", "WAITING_REPLY"}
            or task["status"] == selected_status
        )
        and (
            not search_text
            or search_text
            in " ".join(
                filter(
                    None,
                    [task.get("title"), task.get("description"), task.get("requester")],
                )
            ).casefold()
        )
    ]
    filtered_tasks = sorted(
        filtered_tasks,
        key=lambda task: _task_priority(task, priority_by_task[task["task_id"]].level),
    )

    st.caption(f"검색 결과 {len(filtered_tasks)}건")
    if not filtered_tasks:
        st.info("선택한 조건에 맞는 업무가 없습니다.")
    for task in filtered_tasks:
        priority = priority_by_task[task["task_id"]]
        with st.container(border=True):
            icon_col, content_col, action_col = st.columns([0.4, 5.1, 1.4])
            icon_col.markdown(f"### {priority.emoji}")
            content_col.markdown(f"**{task['title']}**")
            content_col.caption(
                f"{priority.label} · {STATUS_LABELS.get(task['status'], task['status'])} · "
                f"기한 {task.get('due_date') or '없음'} · {task.get('requester') or '요청자 없음'}"
            )
            if task.get("description"):
                content_col.caption(task["description"])
            if action_col.button(
                "상세 보기",
                key=f"open_task_{task['task_id']}",
                width="stretch",
            ):
                st.session_state["selected_operational_task_id"] = task["task_id"]
                st.rerun()
            if task["status"] not in {"COMPLETED", "CANCELLED"} and action_col.button(
                "완료 처리",
                key=f"complete_task_list_{task['task_id']}",
                width="stretch",
            ):
                try:
                    _complete_task_from_dashboard(storage, task)
                except ValueError as exc:
                    st.error(f"완료할 수 없습니다: {exc}")

    selected_task_id = st.session_state.get("selected_operational_task_id")
    selected_task = next(
        (task for task in tasks if task["task_id"] == selected_task_id),
        None,
    )
    if selected_task is None:
        return
    _render_operational_task_detail(storage, selected_task)


def _render_quality_evaluation(settings) -> None:
    st.subheader("15개 대표 시나리오 품질 검증")
    st.write(
        "각 시나리오를 서로 분리된 임시 DB에서 실행하고, 저장소에 확정한 기대 Action·상태·"
        "중복 방지·사용자 확인 여부와 실제 결과를 비교합니다."
    )
    st.info(
        "이 Dataset은 애매한 경계 Case를 의도적으로 많이 포함합니다. 따라서 사용자 확인율은 "
        "실제 운영 메일 비율 예측이 아니라 안전장치 검증 수치입니다."
    )

    mock_col, live_col = st.columns(2)
    if mock_col.button("Mock 15개 즉시 검증", type="primary", use_container_width=True):
        with st.spinner("결정 규칙과 DB 반영을 검증하고 있습니다..."):
            st.session_state["mock_evaluation"] = run_scenario_evaluation(
                settings, MockMailAnalyzer(), mode="MOCK"
            )

    live_disabled = settings.use_mock
    if live_col.button(
        "회사 LLM Live 15개 검증",
        disabled=live_disabled,
        use_container_width=True,
    ):
        with st.spinner("회사 LLM을 호출해 15개 Case를 검증하고 있습니다. 잠시 기다려 주세요..."):
            st.session_state["live_evaluation"] = run_scenario_evaluation(
                settings, build_analyzer(settings), mode="LIVE"
            )
    if live_disabled:
        live_col.caption("API Key가 있는 LIVE 모드에서만 실행할 수 있습니다.")
    else:
        live_col.caption("최대 27회 LLM 분석 호출이 발생하며 Mock 결과와 별도로 기록됩니다.")

    saved_live_paths = list(
        (PROJECT_ROOT / "evidence").glob("live_evaluation_*.json")
    )
    if "live_evaluation" not in st.session_state and saved_live_paths:
        saved_live_reports = [
            load_saved_evaluation_report(path) for path in saved_live_paths
        ]
        st.session_state["live_evaluation"] = max(
            saved_live_reports,
            key=lambda item: item.get("generated_at", ""),
        )

    report_options = []
    if st.session_state.get("mock_evaluation"):
        report_options.append("Mock 회귀")
    if st.session_state.get("live_evaluation"):
        report_options.append("회사 LLM Live")
    if not report_options:
        st.caption("검증 버튼을 누르면 Case별 기대값과 실제 결과 비교표가 여기에 표시됩니다.")
        return

    selected = st.radio("표시할 결과", report_options, horizontal=True)
    report_key = "mock_evaluation" if selected == "Mock 회귀" else "live_evaluation"
    report = st.session_state[report_key]
    if report.get("generated_at"):
        st.success(
            f"저장된 회사 LLM 검증 증적 · {report['generated_at']} · {report.get('model', '-')}"
        )
    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric("통과 시나리오", f"{report['passed_count']}/{report['case_count']}")
    metric_2.metric("시나리오 통과율", f"{report['scenario_pass_rate']:.1%}")
    metric_3.metric("Action 단계 일치율", f"{report['action_step_accuracy']:.1%}")
    metric_4.metric("사용자 확인 비율", f"{report['review_rate']:.1%}")

    if "mail_classification_accuracy" in report:
        st.subheader("세부 Ground Truth KPI")
        detail_1, detail_2, detail_3, detail_4 = st.columns(4)
        detail_1.metric(
            "업무 요청 분류 정확도",
            f"{report['mail_classification_accuracy']:.1%}",
            help=(
                f"{report['mail_classification_correct']}/"
                f"{report['mail_classification_total']} Mail"
            ),
        )
        detail_2.metric(
            "요청사항·기한 추출 정확도",
            f"{report['field_extraction_accuracy']:.1%}",
            help=(
                f"{report['field_extraction_correct']}/"
                f"{report['field_extraction_total']} 필수 필드"
            ),
        )
        detail_3.metric(
            "기존 Task 연결 정확도",
            f"{report['task_link_accuracy']:.1%}",
            help=(
                f"{report['task_link_correct']}/"
                f"{report['task_link_total']} 단일 정답 연결"
            ),
        )
        detail_4.metric(
            "Intent 진단 정확도",
            f"{report['intent_accuracy']:.1%}",
            help=f"{report['intent_correct']}/{report['intent_total']} Mail",
        )
        st.caption(
            "요청사항은 정답 문장과의 단순 문자열 일치가 아니라 사전에 확정한 핵심 의미 "
            "Token Group 포함 여부로 평가합니다. 복수 후보처럼 정답 Task가 하나가 아닌 Case는 "
            "Task ID KPI 분모에서 제외합니다."
        )

        with st.expander("Mail 분류·필드 Ground Truth 상세"):
            mail_kpi_frame = pd.DataFrame(report["mail_kpi_rows"]).rename(
                columns={
                    "mail_id": "Mail ID",
                    "expected_is_task_request": "기대 업무 여부",
                    "actual_is_task_request": "실제 업무 여부",
                    "classification_passed": "분류 일치",
                    "expected_intent": "기대 Intent",
                    "actual_intent": "실제 Intent",
                    "intent_passed": "Intent 일치",
                    "expected_summary_terms": "요청사항 정답 Token",
                    "actual_request_summary": "실제 요청사항",
                    "request_summary_passed": "요청사항 일치",
                    "expected_due_date": "기대 기한",
                    "actual_due_date": "실제 기한",
                    "due_date_passed": "기한 일치",
                }
            )
            st.dataframe(mail_kpi_frame, width="stretch", hide_index=True)

        with st.expander("기존 Task ID 연결 Ground Truth 상세"):
            task_link_frame = pd.DataFrame(report["task_link_rows"]).rename(
                columns={
                    "case_id": "Case",
                    "step_index": "단계 Index",
                    "mail_id": "Mail ID",
                    "expected_task_id": "기대 Task ID",
                    "actual_task_id": "실제 Task ID",
                    "passed": "일치",
                }
            )
            st.dataframe(task_link_frame, width="stretch", hide_index=True)
    else:
        st.warning(
            "이 저장 증적은 세부 Ground Truth KPI 추가 전 결과입니다. 최신 평가를 실행하면 "
            "분류·요청사항/기한·Task ID 정확도를 함께 표시합니다."
        )

    frame = pd.DataFrame(report["rows"])
    frame["결과"] = frame["passed"].map({True: "통과", False: "실패"})
    frame["사용자 확인"] = frame["review_actual"].map({True: "필요", False: "자동 처리"})
    frame = frame.rename(
        columns={
            "case_id": "Case",
            "title": "시나리오",
            "expected_actions": "기대 Action",
            "actual_actions": "실제 Action",
            "failure_reason": "불일치 원인",
            "duration_ms": "처리 시간(ms)",
        }
    )
    st.dataframe(
        frame[
            [
                "Case",
                "시나리오",
                "기대 Action",
                "실제 Action",
                "결과",
                "사용자 확인",
                "불일치 원인",
                "처리 시간(ms)",
            ]
        ],
        width="stretch",
        hide_index=True,
    )
    st.caption(
        f"{report['mode']} · Action {report['total_action_steps']}단계 · "
        f"총 {report['duration_ms'] / 1000:.2f}초. Mock은 Application Logic 회귀 증적이고, "
        "Live 결과만 회사 LLM 품질 증적으로 사용합니다."
    )
    _render_manual_time_benchmark(st.session_state.get("live_evaluation"))


def _clear_manual_benchmark_inputs() -> None:
    for key in list(st.session_state):
        if key.startswith("manual_benchmark_action_"):
            st.session_state.pop(key, None)
    st.session_state.pop("manual_benchmark_work_confirmed", None)


def _render_manual_time_benchmark(live_report: dict | None) -> None:
    st.divider()
    st.subheader("업무 정리시간 비교 · 실사용자 측정")
    st.write(
        "SC-001 신규 업무, SC-002 후속 변경, SC-003 사용자 확인의 대표 Case를 사람이 "
        "직접 읽고 정리한 시간과 같은 Live Case의 Agent 처리시간을 비교합니다."
    )
    st.info(
        "사람의 실제 수행시간이 필요한 KPI입니다. 측정 완료 전에는 시간 단축률을 달성값으로 "
        "기록하지 않습니다. 정답 Action은 측정 종료 후에만 표시됩니다."
    )

    if not live_report or live_report.get("mode") != "LIVE":
        st.warning("저장된 회사 LLM Live 평가 증적이 있어야 같은 Case의 Agent 시간과 비교할 수 있습니다.")
        return

    benchmark_cases = load_manual_benchmark_cases()
    total_steps = sum(len(case["steps"]) for case in benchmark_cases)
    st.caption(
        f"측정 범위: BC-01·BC-04·BC-11, 총 {total_steps}개 Mail 처리 단계 · "
        f"Agent 기준 증적: {live_report.get('generated_at', '-')}"
    )

    started = st.session_state.get("manual_benchmark_started_perf")
    if started is None:
        if st.button("수동 업무 정리 측정 시작", key="manual_benchmark_start"):
            _clear_manual_benchmark_inputs()
            st.session_state.pop("manual_benchmark_result", None)
            st.session_state.pop("manual_benchmark_evidence_path", None)
            st.session_state["manual_benchmark_started_perf"] = perf_counter()
            st.session_state["manual_benchmark_started_at"] = (
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
            st.rerun()
    else:
        st.warning(
            "타이머가 실행 중입니다. 각 Case를 순서대로 읽고 업무 여부·요청사항·기한·연결 "
            "대상을 별도 메모한 뒤, 화면에는 최종 Action을 선택하세요."
        )
        action_options = ["선택"] + [action.value for action in AgentAction]
        for case in benchmark_cases:
            with st.expander(f"{case['case_id']} · {case['title']}", expanded=True):
                st.caption("각 Case는 독립된 업무 상황입니다. 위 단계에서 만든 Task 상태를 다음 단계에 이어서 적용합니다.")
                for step in case["steps"]:
                    st.markdown(
                        f"**{step['step_index'] + 1}단계 · {step['mail_id']} · "
                        f"{step['direction']}**"
                    )
                    st.write(f"제목: {step['subject']}")
                    st.write(step["body"])
                    action_key = (
                        f"manual_benchmark_action_{case['case_id']}_{step['step_index']}"
                    )
                    st.selectbox(
                        "내가 판단한 다음 Action",
                        action_options,
                        key=action_key,
                        format_func=lambda value: (
                            value
                            if value == "선택"
                            else f"{ACTION_LABELS[value]} ({value})"
                        ),
                    )

        st.checkbox(
            "모든 단계에서 업무 여부·요청사항·기한·연결 대상을 메모하고 Action 선택을 완료했습니다.",
            key="manual_benchmark_work_confirmed",
        )
        stop_col, cancel_col = st.columns(2)
        if stop_col.button(
            "측정 종료 및 결과 계산",
            type="primary",
            key="manual_benchmark_stop",
            use_container_width=True,
        ):
            answers = {}
            incomplete = []
            for case in benchmark_cases:
                for step in case["steps"]:
                    widget_key = (
                        f"manual_benchmark_action_{case['case_id']}_{step['step_index']}"
                    )
                    selected_action = st.session_state.get(widget_key, "선택")
                    answer_key = f"{case['case_id']}:{step['step_index']}"
                    if selected_action == "선택":
                        incomplete.append(answer_key)
                    else:
                        answers[answer_key] = selected_action
            if incomplete:
                st.warning("모든 Mail 단계의 Action을 선택해야 측정을 종료할 수 있습니다.")
            elif not st.session_state.get("manual_benchmark_work_confirmed"):
                st.warning("수동 정리 항목을 모두 메모했는지 확인해 주세요.")
            else:
                completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
                duration_ms = max(
                    1,
                    round(
                        (perf_counter() - st.session_state["manual_benchmark_started_perf"])
                        * 1000
                    ),
                )
                result = calculate_manual_benchmark_result(
                    answers,
                    manual_duration_ms=duration_ms,
                    agent_report=live_report,
                    started_at=st.session_state["manual_benchmark_started_at"],
                    completed_at=completed_at,
                )
                evidence_path = save_manual_benchmark_evidence(result)
                st.session_state["manual_benchmark_result"] = result
                st.session_state["manual_benchmark_evidence_path"] = str(evidence_path)
                st.session_state.pop("manual_benchmark_started_perf", None)
                st.session_state.pop("manual_benchmark_started_at", None)
                _clear_manual_benchmark_inputs()
                st.rerun()
        if cancel_col.button(
            "측정 취소",
            key="manual_benchmark_cancel",
            use_container_width=True,
        ):
            st.session_state.pop("manual_benchmark_started_perf", None)
            st.session_state.pop("manual_benchmark_started_at", None)
            _clear_manual_benchmark_inputs()
            st.rerun()

    result = st.session_state.get("manual_benchmark_result")
    if result:
        time_rate = result["time_reduction_rate"]
        result_1, result_2, result_3, result_4 = st.columns(4)
        result_1.metric("사람 수동 정리", f"{result['manual_duration_ms'] / 1000:.2f}초")
        result_2.metric("Agent 동일 Case", f"{result['agent_duration_ms'] / 1000:.2f}초")
        result_3.metric(
            "시간 단축률",
            "산정 제외" if time_rate is None else f"{time_rate:.1%}",
        )
        result_4.metric(
            "수동 Action 정확도",
            f"{result['manual_action_correct']}/{result['manual_action_total']}",
        )
        if not result["kpi_eligible"]:
            st.warning(
                "수동 Action이 정답과 달라 동등 정확도 조건을 충족하지 못했습니다. 이 실행의 "
                "시간 단축률은 공식 KPI에서 제외하고 다시 측정하세요."
            )
        elif result["target_met"]:
            st.success("동일 Case·동등 정확도 조건에서 업무 정리시간 30% 이상 단축 목표를 달성했습니다.")
        else:
            st.warning("동일 Case·동등 정확도 조건에서 시간 단축률 30% 목표에 미달했습니다.")

        result_frame = pd.DataFrame(result["rows"]).rename(
            columns={
                "case_id": "Case",
                "step_index": "단계 Index",
                "mail_id": "Mail ID",
                "expected_action": "기대 Action",
                "actual_action": "수동 판단 Action",
                "passed": "일치",
            }
        )
        st.dataframe(result_frame, width="stretch", hide_index=True)
        evidence_path = st.session_state.get("manual_benchmark_evidence_path")
        if evidence_path:
            st.caption(f"측정 증적 저장: {evidence_path}")


@st.fragment(run_every="60s")
def _render_automatic_gmail_sync(storage, settings) -> None:
    operation_settings = storage.get_operation_settings()
    if not operation_settings["gmail_auto_sync_enabled"]:
        return

    interval_minutes = int(operation_settings["gmail_sync_interval_minutes"])
    now = datetime.now()
    last_check = st.session_state.get("gmail_auto_sync_last_check")
    if last_check and (now - last_check).total_seconds() < interval_minutes * 60:
        return

    try:
        cached_mails = (
            st.session_state.get("gmail_test_mails") if last_check is None else None
        )
        source = _GmailSyncSource(storage, cached_mails)
        report = MailSyncService(
            settings=settings,
            storage=storage,
            analyzer=build_operational_analyzer(settings, storage),
            source=source,
            source_name="GMAIL",
        ).run_once()
        st.session_state["gmail_test_mails"] = source.loaded_mails or []
        st.session_state["gmail_auto_sync_last_check"] = now
        if report.status == "FAILED":
            st.session_state["gmail_auto_sync_error"] = report.error_type
            st.warning(f"Gmail 새 메일 확인 실패 · {report.error_type}")
            return
        st.session_state.pop("gmail_auto_sync_error", None)
        if report.pending_count:
            st.session_state["batch_flash"] = {
                "success": report.succeeded_count,
                "failed": [
                    {"mail_id": mail_id, "error": report.error_type or "ProcessingError"}
                    for mail_id in report.failed_mail_ids
                ],
                "message": (
                    f"Gmail에서 새 메일 {report.pending_count}건을 확인해 자동 분류했습니다."
                ),
            }
            st.rerun()
    except Exception as exc:
        error_type = type(exc).__name__
        st.session_state["gmail_auto_sync_last_check"] = now
        st.session_state["gmail_auto_sync_error"] = error_type
        st.warning(f"Gmail 새 메일 확인 실패 · {error_type}")


def _render_operation_settings(storage, gmail_summary: dict, mails) -> None:
    st.subheader("연결 및 설정")
    st.caption("메일 연결 상태와 개인 업무 우선순위 기준을 관리합니다.")

    settings_flash = st.session_state.pop("operation_settings_flash", None)
    if settings_flash:
        st.success(settings_flash)

    with st.container(border=True):
        st.markdown("### 메일 연결")
        if gmail_summary["credentials_ready"] and gmail_summary["token_ready"]:
            st.success("Gmail 읽기 전용 연결됨")
            st.caption(
                f"제한 Query · {gmail_summary['query']} · 최대 {gmail_summary['max_results']}건"
            )
        else:
            st.warning("Gmail 사용자 승인이 필요합니다.")
        st.caption("Outlook / Microsoft Graph는 Gmail 실전 Workflow 검증 후 연결합니다.")

    sync_runs = storage.list_sync_runs(source="GMAIL", limit=10)
    if sync_runs:
        latest_sync = sync_runs[0]
        status_label = {
            "SUCCESS": "정상",
            "PARTIAL": "일부 실패",
            "FAILED": "실패",
            "RUNNING": "실행 중",
        }.get(latest_sync["status"], latest_sync["status"])
        st.caption(
            f"최근 Gmail 자동 실행 · {status_label} · "
            f"성공 {latest_sync['succeeded_count']}건 · "
            f"실패 {latest_sync['failed_count']}건 · "
            f"재시도 {latest_sync['retry_count']}회"
        )
        with st.expander("최근 자동 실행 기록"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "시작 시각": run["started_at"],
                            "상태": {
                                "SUCCESS": "정상",
                                "PARTIAL": "일부 실패",
                                "FAILED": "실패",
                                "RUNNING": "실행 중",
                            }.get(run["status"], run["status"]),
                            "가져옴": run["fetched_count"],
                            "신규": run["pending_count"],
                            "성공": run["succeeded_count"],
                            "실패": run["failed_count"],
                            "중복": run["duplicate_count"],
                            "재시도": run["retry_count"],
                            "오류 종류": run.get("error_type") or "-",
                        }
                        for run in sync_runs
                    ]
                ),
                width="stretch",
                hide_index=True,
            )

    st.markdown("### Gmail 자동 정리")
    operation_settings = storage.get_operation_settings()
    with st.form("gmail_auto_sync_form"):
        auto_sync_enabled = st.checkbox(
            "새 메일을 자동으로 Task에 반영",
            value=bool(operation_settings["gmail_auto_sync_enabled"]),
            help=(
                "제한된 Gmail Label의 읽기 전용 메일만 확인합니다. "
                "이미 처리된 mail_id는 다시 분석하지 않습니다."
            ),
        )
        sync_interval = int(
            st.number_input(
                "자동 확인 주기(분)",
                min_value=1,
                max_value=60,
                value=int(operation_settings["gmail_sync_interval_minutes"]),
                disabled=not auto_sync_enabled,
            )
        )
        save_auto_sync = st.form_submit_button("자동 정리 설정 저장", type="primary")
    if save_auto_sync:
        try:
            storage.update_operation_settings(
                gmail_auto_sync_enabled=auto_sync_enabled,
                gmail_sync_interval_minutes=sync_interval,
            )
            st.session_state.pop("gmail_auto_sync_last_check", None)
            st.session_state["operation_settings_flash"] = (
                "Gmail 자동 정리 설정을 저장했습니다."
            )
            st.rerun()
        except ValueError as exc:
            st.error(f"자동 정리 설정을 저장할 수 없습니다: {exc}")

    st.markdown("### 기한·회신 대기 기준")
    settings = storage.get_priority_settings()
    with st.form("priority_threshold_form"):
        soon_col, later_col, waiting_col = st.columns(3)
        due_soon_days = int(
            soon_col.number_input(
                "🟠 기한 임박 기준",
                min_value=1,
                max_value=29,
                value=settings["due_soon_days"],
                help="이 일수 이내의 업무를 우선 처리로 표시합니다.",
            )
        )
        due_later_days = int(
            later_col.number_input(
                "🔵 예정 업무 기준",
                min_value=2,
                max_value=30,
                value=settings["due_later_days"],
                help="기한이 이 일수 이내인 업무를 예정 업무로 표시합니다.",
            )
        )
        waiting_attention_days = int(
            waiting_col.number_input(
                "🟡 회신 대기 확인",
                min_value=1,
                max_value=30,
                value=settings["waiting_attention_days"],
                help="이 기간 이상 회신이 없으면 우선 확인합니다.",
            )
        )
        if st.form_submit_button("기준 저장", type="primary"):
            try:
                storage.update_priority_settings(
                    {
                        "due_soon_days": due_soon_days,
                        "due_later_days": due_later_days,
                        "waiting_attention_days": waiting_attention_days,
                    }
                )
                st.success("우선순위 기준을 저장했습니다.")
            except ValueError as exc:
                st.error(f"기준을 저장할 수 없습니다: {exc}")

    st.markdown("### 고객사·연락처·키워드 Rule")
    st.caption(
        "발신자와 키워드는 중요도 신호로만 사용합니다. 완료·취소·기한은 Rule만으로 확정하지 않습니다."
    )
    with st.form("priority_rule_form", clear_on_submit=True):
        name = st.text_input("Rule 이름", placeholder="예: ABC 고객사")
        rule_type = st.selectbox(
            "조건",
            list(PRIORITY_RULE_LABELS),
            format_func=lambda value: PRIORITY_RULE_LABELS[value],
        )
        pattern = st.text_input(
            "일치 값",
            placeholder="abc.co.kr 또는 owner@abc.co.kr 또는 장애",
        )
        importance = st.selectbox(
            "적용 중요도",
            [1, 2, 3, 4],
            index=1,
            format_func=lambda value: (
                f"{PRIORITY_PRESENTATION[PriorityLevel(f'P{value}')][0]} P{value}"
            ),
        )
        add_rule = st.form_submit_button("Rule 추가", type="primary")
    if add_rule:
        try:
            storage.add_priority_rule(
                name=name,
                rule_type=rule_type,
                pattern=pattern,
                importance=importance,
            )
            st.success("중요도 Rule을 추가했습니다.")
            st.rerun()
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            st.error(f"Rule을 추가할 수 없습니다: {message}")

    rules = storage.list_priority_rules()
    if not rules:
        st.info("등록된 사용자 Rule이 없습니다. 기한과 회신 대기 기준으로 우선순위를 계산합니다.")
    else:
        rule_frame = pd.DataFrame(
            [
                {
                    "사용": "켜짐" if rule["enabled"] else "꺼짐",
                    "Rule": rule["name"],
                    "조건": PRIORITY_RULE_LABELS.get(
                        rule["rule_type"], rule["rule_type"]
                    ),
                    "일치 값": rule["pattern"],
                    "중요도": f"P{rule['importance']}",
                }
                for rule in rules
            ]
        )
        st.dataframe(rule_frame, width="stretch", hide_index=True)
        selected_rule = st.selectbox(
            "관리할 Rule",
            rules,
            format_func=lambda item: f"{item['name']} · {item['pattern']}",
        )
        toggle_col, delete_col = st.columns(2)
        toggle_label = "Rule 끄기" if selected_rule["enabled"] else "Rule 켜기"
        if toggle_col.button(toggle_label, width="stretch"):
            storage.set_priority_rule_enabled(
                selected_rule["rule_id"], not selected_rule["enabled"]
            )
            st.rerun()
        if delete_col.button("Rule 삭제", width="stretch"):
            storage.delete_priority_rule(selected_rule["rule_id"])
            st.rerun()

    st.markdown("### 광고·자동발송 제외 Rule")
    st.caption(
        "새 메일의 정확한 발신자·도메인·제목만 확인합니다. "
        "본문 키워드로는 자동 제외하지 않으며 적용 결과는 IGNORE 근거로 남습니다."
    )
    with st.form("mail_filter_rule_form", clear_on_submit=True):
        filter_name = st.text_input("제외 Rule 이름", placeholder="예: 사내 뉴스레터")
        filter_type = st.selectbox(
            "제외 조건",
            list(MAIL_FILTER_RULE_LABELS),
            format_func=lambda value: MAIL_FILTER_RULE_LABELS[value],
        )
        filter_pattern = st.text_input(
            "제외 일치 값",
            placeholder="newsletter@example.com 또는 example.com 또는 뉴스레터",
        )
        if filter_pattern.strip():
            preview_rule = {
                "name": filter_name or "미리보기",
                "rule_type": filter_type,
                "pattern": filter_pattern,
                "enabled": True,
            }
            preview_count = sum(
                match_mail_filter_rule(mail, [preview_rule]) is not None
                for mail in mails
            )
            st.caption(f"현재 입력 Source 미리보기 · {preview_count}건 일치")
        add_filter_rule = st.form_submit_button("제외 Rule 추가", type="primary")
    if add_filter_rule:
        try:
            storage.add_mail_filter_rule(
                name=filter_name,
                rule_type=filter_type,
                pattern=filter_pattern,
            )
            st.session_state["operation_settings_flash"] = (
                "Mail 제외 Rule을 추가했습니다. 다음 신규 메일부터 적용합니다."
            )
            st.rerun()
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            st.error(f"제외 Rule을 추가할 수 없습니다: {message}")

    filter_rules = storage.list_mail_filter_rules()
    if not filter_rules:
        st.info("등록된 제외 Rule이 없습니다. 비업무 Mail은 Agent 분석 후 IGNORE로 분류합니다.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "사용": "켜짐" if rule["enabled"] else "꺼짐",
                        "Rule": rule["name"],
                        "조건": MAIL_FILTER_RULE_LABELS.get(
                            rule["rule_type"], rule["rule_type"]
                        ),
                        "일치 값": rule["pattern"],
                    }
                    for rule in filter_rules
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        selected_filter_rule = st.selectbox(
            "관리할 제외 Rule",
            filter_rules,
            format_func=lambda item: f"{item['name']} · {item['pattern']}",
        )
        filter_toggle_col, filter_delete_col = st.columns(2)
        filter_toggle_label = (
            "제외 Rule 끄기" if selected_filter_rule["enabled"] else "제외 Rule 켜기"
        )
        if filter_toggle_col.button(filter_toggle_label, width="stretch"):
            storage.set_mail_filter_rule_enabled(
                selected_filter_rule["rule_id"],
                not selected_filter_rule["enabled"],
            )
            st.rerun()
        if filter_delete_col.button("제외 Rule 삭제", width="stretch"):
            storage.delete_mail_filter_rule(selected_filter_rule["rule_id"])
            st.rerun()

    st.markdown("### 데이터 내보내기와 복구")
    st.caption(
        "Task와 History만 내려받습니다. Gmail 원문과 API Key는 내보내기 파일에 포함하지 않습니다."
    )
    export_col, history_export_col = st.columns(2)
    tasks = storage.list_tasks()
    histories = storage.list_histories()
    task_csv = pd.DataFrame(tasks).to_csv(index=False).encode("utf-8-sig")
    export_col.download_button(
        "Task CSV 내려받기",
        data=task_csv,
        file_name=f"mailtaskagent-tasks-{date.today().isoformat()}.csv",
        mime="text/csv",
        width="stretch",
    )
    history_export_col.download_button(
        "History JSON 내려받기",
        data=json.dumps(histories, ensure_ascii=False, indent=2),
        file_name=f"mailtaskagent-history-{date.today().isoformat()}.json",
        mime="application/json",
        width="stretch",
    )
    if st.button("SQLite 복구용 백업 생성", width="stretch"):
        try:
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            backup_path = storage.backup_to(
                PROJECT_ROOT / "data" / "backups" / f"mailtaskagent-{stamp}.db"
            )
            st.session_state["operation_settings_flash"] = (
                f"복구용 백업을 생성했습니다: {backup_path}"
            )
            st.rerun()
        except Exception as exc:
            st.error(f"백업을 생성할 수 없습니다: {type(exc).__name__}")

    st.markdown("### Slack 알림")
    slack_settings = load_slack_notification_settings()
    if slack_settings.enabled and slack_settings.configured:
        st.success("Slack 운영 알림 · 연결 준비됨")
    elif slack_settings.enabled:
        st.warning("Slack 운영 알림 · Webhook 설정 필요")
    else:
        st.info("Slack 운영 알림 · 꺼짐")
    st.caption(
        "Gmail 처리 실패와 검토 필요 건수만 알립니다. Mail 원문, Task 제목, 사용자 정보와 "
        "Webhook URL은 화면·로그·알림에 표시하지 않습니다."
    )


def _render_automation_center(storage, mails) -> None:
    st.subheader("자동화 설정")
    st.caption("업무 우선순위를 정하고 광고·반복 메일을 제외하는 개인 기준을 설정합니다.")
    settings_flash = st.session_state.pop("operation_settings_flash", None)
    if settings_flash:
        st.success(settings_flash)

    operation_settings = storage.get_operation_settings()
    priority_rules = storage.list_priority_rules()
    filter_rules = storage.list_mail_filter_rules()
    active_priority = sum(rule["enabled"] for rule in priority_rules)
    active_filters = sum(rule["enabled"] for rule in filter_rules)
    summary_1, summary_2, summary_3 = st.columns(3)
    summary_1.metric(
        "Agent 상태",
        "실행 중" if operation_settings["gmail_auto_sync_enabled"] else "일시정지",
    )
    summary_2.metric("중요 발신자·키워드", f"{active_priority}개")
    summary_3.metric("광고·반복 메일 제외", f"{active_filters}개")

    priority_tab, filter_tab, auto_tab = st.tabs(
        ["⭐ 우선순위 기준", "🚫 광고·반복 메일 제외", "⚙️ 실행 주기"]
    )
    with auto_tab:
        st.markdown("### Agent 실행 주기")
        st.write(
            "Gmail 연결 후 Agent는 기본 실행됩니다. 이 값은 새 메일을 확인하는 간격이며, "
            "Agent 일시정지와 재실행은 사이드바에서 할 수 있습니다."
        )
        with st.form("gmail_auto_sync_form_v2"):
            sync_interval = int(
                st.number_input(
                    "새 메일 확인 주기(분)",
                    min_value=1,
                    max_value=60,
                    value=int(operation_settings["gmail_sync_interval_minutes"]),
                )
            )
            save_auto_sync = st.form_submit_button("실행 주기 저장", type="primary")
        if save_auto_sync:
            try:
                storage.update_operation_settings(
                    gmail_auto_sync_enabled=bool(
                        operation_settings["gmail_auto_sync_enabled"]
                    ),
                    gmail_sync_interval_minutes=sync_interval,
                )
                st.session_state.pop("gmail_auto_sync_last_check", None)
                st.session_state["operation_settings_flash"] = "Agent 실행 주기를 저장했습니다."
                st.rerun()
            except ValueError as exc:
                st.error(f"실행 주기를 저장할 수 없습니다: {exc}")

    with priority_tab:
        st.markdown("### 우선순위 계산 기준")
        st.write(
            "우선순위는 긴급도(기한·회신 대기)와 중요도(VIP 발신자·고객사 도메인·"
            "중요 키워드·사용자 직접 지정)를 함께 반영해 P1~P4로 계산합니다."
        )
        st.markdown("#### 기한·회신 대기 시간 기준")
        st.caption("아래 3개는 사용자가 일수로 조정할 수 있는 긴급도 경계값입니다.")
        settings = storage.get_priority_settings()
        with st.form("priority_threshold_form_v2"):
            soon_col, later_col, waiting_col = st.columns(3)
            due_soon_days = int(
                soon_col.number_input(
                    "🟠 기한 임박",
                    min_value=1,
                    max_value=29,
                    value=settings["due_soon_days"],
                    help="이 일수 이내의 업무를 우선 처리로 표시합니다.",
                )
            )
            due_later_days = int(
                later_col.number_input(
                    "🔵 예정 업무",
                    min_value=2,
                    max_value=30,
                    value=settings["due_later_days"],
                    help="이 일수 이내인 업무를 예정 업무로 표시합니다.",
                )
            )
            waiting_attention_days = int(
                waiting_col.number_input(
                    "🟡 회신 대기 확인",
                    min_value=1,
                    max_value=30,
                    value=settings["waiting_attention_days"],
                    help="이 기간 이상 회신이 없으면 우선 확인합니다.",
                )
            )
            save_thresholds = st.form_submit_button("시간 기준 저장")
        if save_thresholds:
            try:
                storage.update_priority_settings(
                    {
                        "due_soon_days": due_soon_days,
                        "due_later_days": due_later_days,
                        "waiting_attention_days": waiting_attention_days,
                    }
                )
                st.success("우선순위 시간 기준을 저장했습니다.")
            except ValueError as exc:
                st.error(f"기준을 저장할 수 없습니다: {exc}")

        st.markdown("#### VIP·고객사·중요 키워드 기준")
        st.caption(
            "발신자·도메인·키워드 규칙과 업무별 사용자 직접 지정 중요도도 계산에 포함됩니다. "
            "이 기준만으로 완료·취소·기한을 임의로 확정하지는 않습니다."
        )
        with st.form("priority_rule_form_v2", clear_on_submit=True):
            name = st.text_input("표시 이름", placeholder="예: ABC 고객사 또는 김부장님")
            rule_type = st.selectbox(
                "무엇을 확인할까요?",
                list(PRIORITY_RULE_LABELS),
                format_func=lambda value: PRIORITY_RULE_LABELS[value],
            )
            pattern = st.text_input(
                "이메일·도메인·키워드",
                placeholder="owner@abc.co.kr, abc.co.kr 또는 장애",
            )
            importance = st.selectbox(
                "표시할 중요도",
                [1, 2, 3, 4],
                index=1,
                format_func=lambda value: (
                    f"{PRIORITY_PRESENTATION[PriorityLevel(f'P{value}')][0]} P{value}"
                ),
            )
            add_rule = st.form_submit_button("중요 기준 추가", type="primary")
        if add_rule:
            try:
                storage.add_priority_rule(
                    name=name,
                    rule_type=rule_type,
                    pattern=pattern,
                    importance=importance,
                )
                st.rerun()
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                st.error(f"중요 기준을 추가할 수 없습니다: {message}")

        priority_rules = storage.list_priority_rules()
        if not priority_rules:
            st.info("등록된 VIP·고객사·중요 키워드가 없습니다. 기한과 회신 대기 기준만 사용합니다.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "사용": "켜짐" if rule["enabled"] else "꺼짐",
                            "이름": rule["name"],
                            "구분": PRIORITY_RULE_LABELS.get(rule["rule_type"], rule["rule_type"]),
                            "일치 값": rule["pattern"],
                            "중요도": f"P{rule['importance']}",
                        }
                        for rule in priority_rules
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
            selected_rule = st.selectbox(
                "수정할 중요 기준",
                priority_rules,
                format_func=lambda item: f"{item['name']} · {item['pattern']}",
                key="priority_rule_selection_v2",
            )
            toggle_col, delete_col = st.columns(2)
            if toggle_col.button(
                "사용 중지" if selected_rule["enabled"] else "다시 사용",
                width="stretch",
                key="priority_rule_toggle_v2",
            ):
                storage.set_priority_rule_enabled(
                    selected_rule["rule_id"], not selected_rule["enabled"]
                )
                st.rerun()
            if delete_col.button("삭제", width="stretch", key="priority_rule_delete_v2"):
                storage.delete_priority_rule(selected_rule["rule_id"])
                st.rerun()

    with filter_tab:
        st.markdown("### 광고·뉴스레터·자동발송 메일 제외")
        st.write("정확한 발신자, 도메인 또는 제목 키워드가 일치하는 새 메일은 업무로 만들지 않습니다.")
        st.caption("본문 내용만으로 자동 제외하지 않으며, 제외 결과도 Agent 처리 기록에 남깁니다.")
        with st.form("mail_filter_rule_form_v2", clear_on_submit=True):
            filter_name = st.text_input("표시 이름", placeholder="예: 사내 뉴스레터")
            filter_type = st.selectbox(
                "무엇을 제외할까요?",
                list(MAIL_FILTER_RULE_LABELS),
                format_func=lambda value: MAIL_FILTER_RULE_LABELS[value],
            )
            filter_pattern = st.text_input(
                "이메일·도메인·제목 키워드",
                placeholder="newsletter@example.com, example.com 또는 뉴스레터",
            )
            if filter_pattern.strip():
                preview_rule = {
                    "name": filter_name or "미리보기",
                    "rule_type": filter_type,
                    "pattern": filter_pattern,
                    "enabled": True,
                }
                preview_count = sum(
                    match_mail_filter_rule(mail, [preview_rule]) is not None for mail in mails
                )
                st.caption(f"현재 메일 기준으로 {preview_count}건이 일치합니다.")
            add_filter_rule = st.form_submit_button("제외 기준 추가", type="primary")
        if add_filter_rule:
            try:
                storage.add_mail_filter_rule(
                    name=filter_name,
                    rule_type=filter_type,
                    pattern=filter_pattern,
                )
                st.rerun()
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                st.error(f"제외 기준을 추가할 수 없습니다: {message}")

        filter_rules = storage.list_mail_filter_rules()
        if not filter_rules:
            st.info("등록된 제외 기준이 없습니다. 비업무 메일은 Agent 분석 후 제외됩니다.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "사용": "켜짐" if rule["enabled"] else "꺼짐",
                            "이름": rule["name"],
                            "구분": MAIL_FILTER_RULE_LABELS.get(rule["rule_type"], rule["rule_type"]),
                            "일치 값": rule["pattern"],
                        }
                        for rule in filter_rules
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
            selected_filter_rule = st.selectbox(
                "수정할 제외 기준",
                filter_rules,
                format_func=lambda item: f"{item['name']} · {item['pattern']}",
                key="filter_rule_selection_v2",
            )
            toggle_col, delete_col = st.columns(2)
            if toggle_col.button(
                "사용 중지" if selected_filter_rule["enabled"] else "다시 사용",
                width="stretch",
                key="filter_rule_toggle_v2",
            ):
                storage.set_mail_filter_rule_enabled(
                    selected_filter_rule["rule_id"], not selected_filter_rule["enabled"]
                )
                st.rerun()
            if delete_col.button("삭제", width="stretch", key="filter_rule_delete_v2"):
                storage.delete_mail_filter_rule(selected_filter_rule["rule_id"])
                st.rerun()


def _render_connection_and_data_settings(storage, gmail_summary: dict) -> None:
    st.subheader("설정")
    st.caption("메일 연결, 운영 알림과 데이터 백업을 관리합니다.")
    connection_tab, data_tab = st.tabs(["🔗 연결·알림", "🗄️ 데이터·복구"])

    with connection_tab:
        mail_col, slack_col = st.columns(2)
        with mail_col.container(border=True):
            st.markdown("### Gmail")
            if gmail_summary["credentials_ready"] and gmail_summary["token_ready"]:
                st.success("읽기 전용 연결됨")
                st.caption(f"제한 Query · {gmail_summary['query']}")
            else:
                st.warning("사용자 승인이 필요합니다.")
            st.caption("Outlook / Microsoft Graph는 Gmail Workflow 검증 이후 연결합니다.")
        with slack_col.container(border=True):
            st.markdown("### Slack 운영 알림")
            slack_settings = load_slack_notification_settings()
            if slack_settings.enabled and slack_settings.configured:
                st.success("연결 준비됨")
            elif slack_settings.enabled:
                st.warning("Webhook 설정 필요")
            else:
                st.info("꺼짐")
            st.caption("처리 실패와 검토 필요 건수만 알리며 메일 원문과 사용자 정보는 보내지 않습니다.")

    with data_tab:
        st.markdown("### 데이터 내보내기와 복구")
        st.caption("업무와 변경 기록만 내려받습니다. Gmail 원문과 API Key는 포함하지 않습니다.")
        export_col, history_export_col = st.columns(2)
        tasks = storage.list_tasks()
        histories = storage.list_histories()
        export_col.download_button(
            "업무 CSV 내려받기",
            data=pd.DataFrame(tasks).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"mailtaskagent-tasks-{date.today().isoformat()}.csv",
            mime="text/csv",
            width="stretch",
        )
        history_export_col.download_button(
            "변경 기록 JSON 내려받기",
            data=json.dumps(histories, ensure_ascii=False, indent=2),
            file_name=f"mailtaskagent-history-{date.today().isoformat()}.json",
            mime="application/json",
            width="stretch",
        )
        if st.button("복구용 백업 생성", width="stretch", key="create_database_backup_v2"):
            try:
                stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
                backup_path = storage.backup_to(
                    PROJECT_ROOT / "data" / "backups" / f"mailtaskagent-{stamp}.db"
                )
                st.success(f"복구용 백업을 생성했습니다: {backup_path}")
            except Exception as exc:
                st.error(f"백업을 생성할 수 없습니다: {type(exc).__name__}")


def _render_operations_monitoring(storage, settings, mails, selected_source: str) -> None:
    st.subheader("운영 상태")
    st.caption("자동 수집과 Agent 처리 상태를 점검하는 운영 화면입니다. 일상 업무는 내 업무에서 관리합니다.")
    _render_operation_status_bar(
        storage,
        gmail_connected=selected_source == GMAIL_TEST_SOURCE,
    )
    monitoring_view = st.radio(
        "운영 화면",
        ["자동 실행", "메일 처리 내역", "시스템 로그"],
        horizontal=True,
        label_visibility="collapsed",
        key="monitoring_view",
    )

    if monitoring_view == "메일 처리 내역":
        st.markdown("### 메일 처리 내역")
        st.caption("가져온 메일이 어떤 업무로 정리되었는지 확인하고 실패 건을 다시 처리합니다.")
        _render_mailbox(storage, settings, mails, selected_source, demo_mode=False)
        return
    if monitoring_view == "시스템 로그":
        st.markdown("### 시스템 로그")
        st.caption("분석·후보 검색·판단·검증·DB 반영 단계와 오류를 확인합니다.")
        _render_event_log(storage, [mail.mail_id for mail in mails])
        return

    sync_runs = storage.list_sync_runs(source="GMAIL", limit=10)
    latest = sync_runs[0] if sync_runs else None
    latest_status = (
        {
            "SUCCESS": "정상",
            "PARTIAL": "일부 실패",
            "FAILED": "실패",
            "RUNNING": "실행 중",
        }.get(latest["status"], latest["status"])
        if latest
        else "기록 없음"
    )
    _render_summary_cards(
        [
            ("최근 실행", latest_status, "purple"),
            ("신규 메일", f"{latest['pending_count'] if latest else 0}건", "orange"),
            ("처리 성공", f"{latest['succeeded_count'] if latest else 0}건", "yellow"),
            ("처리 실패", f"{latest['failed_count'] if latest else 0}건", "red"),
        ]
    )

    st.markdown("### Gmail 자동 실행 기록")
    if not sync_runs:
        st.info("아직 Gmail 자동 실행 기록이 없습니다.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "시작 시각": datetime.fromisoformat(run["started_at"])
                        .astimezone()
                        .strftime("%m-%d %H:%M:%S"),
                        "상태": {
                            "SUCCESS": "정상",
                            "PARTIAL": "일부 실패",
                            "FAILED": "실패",
                            "RUNNING": "실행 중",
                        }.get(run["status"], run["status"]),
                        "신규": run["pending_count"],
                        "성공": run["succeeded_count"],
                        "실패": run["failed_count"],
                        "중복": run["duplicate_count"],
                        "재시도": run["retry_count"],
                    }
                    for run in sync_runs
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    st.markdown("### Gmail 실메일 수용시험")
    pilot_report = evaluate_gmail_pilot(
        load_gmail_pilot_cases(),
        storage.list_mails(),
        storage.list_processing_results(),
    )
    _render_summary_cards(
        [
            ("수신", f"{pilot_report['observed_cases']}/20", "purple"),
            ("통과", f"{pilot_report['passed_cases']}건", "yellow"),
            ("실패", f"{pilot_report['failed_cases']}건", "red"),
            ("대기", f"{pilot_report['pending_cases']}건", "orange"),
        ]
    )
    if pilot_report["status"] == "PASSED":
        st.success("실메일 20건의 방향·Thread·Action·사용자 확인 결과가 모두 일치합니다.")
    else:
        st.info("별도 송신 Gmail 계정으로 GL-001~020을 송수신하면 결과가 자동 집계됩니다.")
    with st.expander("20건 상세 결과"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Case": row["case_id"],
                        "상태": row["status"],
                        "기대 방향": row["expected_direction"],
                        "실제 방향": row["actual_direction"] or "-",
                        "기대 Action": row["expected_action"],
                        "실제 Action": row["actual_action"] or "-",
                    }
                    for row in pilot_report["cases"]
                ]
            ),
            width="stretch",
            hide_index=True,
        )


def main() -> None:
    st.set_page_config(page_title="MailTaskAgent", page_icon="📬", layout="wide")
    _apply_styles()
    settings = load_settings()
    gmail_summary = _gmail_connection_summary()
    gmail_connected = (
        gmail_summary["credentials_ready"] and gmail_summary["token_ready"]
    )
    app_mode = _render_mode_entry(gmail_connected=gmail_connected)
    if app_mode is None:
        return
    demo_mode = app_mode == DEMO_MODE
    storage = SQLiteStorage(_database_path_for_mode(settings.database_path, app_mode))
    _initialize_storage_or_stop(storage)
    synthetic_mails = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")

    if demo_mode:
        st.title("MailTaskAgent")
        st.write(
            "메일을 업무로 바꾸고, 후속 변경과 확인이 필요한 결정을 놓치지 않게 관리합니다."
        )

    with st.sidebar:
        st.title("MailTaskAgent")
        operation_page = None
        if demo_mode:
            st.caption("MVP 시연·검증")
            if st.button("실제 업무 화면으로 돌아가기", width="stretch"):
                st.session_state["app_mode"] = OPERATION_MODE
                st.session_state.pop("selected_mail_source", None)
                st.session_state.pop("gmail_test_mails", None)
                st.rerun()
            st.divider()
        else:
            st.caption("메일 기반 업무 관리")
            st.subheader("메뉴")
            operation_page = st.radio(
                "주 메뉴",
                OPERATION_PAGES,
                label_visibility="collapsed",
                key="operation_page",
            )
            st.divider()

        if demo_mode:
            st.subheader("연동 상태")
            if settings.use_mock:
                st.warning("MOCK · 합성 Mail 기능 검증")
            else:
                st.success(f"LIVE · {settings.model}")
            source_options = [SYNTHETIC_MAIL_SOURCE]
            if gmail_connected:
                source_options.append(GMAIL_TEST_SOURCE)
            selected_source = st.radio(
                "입력 Source",
                source_options,
                key="selected_mail_source",
            )
        else:
            selected_source = (
                GMAIL_TEST_SOURCE if gmail_connected else SYNTHETIC_MAIL_SOURCE
            )
            st.session_state["selected_mail_source"] = selected_source

        if demo_mode:
            if gmail_connected:
                st.success("Gmail OAuth · 읽기 전용 연결됨")
                st.caption(f"제한 Query · {gmail_summary['query']}")
            elif gmail_summary["credentials_ready"]:
                st.warning("Gmail OAuth · 사용자 승인 필요")
            else:
                st.caption("Gmail OAuth · 선택 연동 전")
        else:
            st.caption("MailTaskAgent")
            st.markdown("🟢 Gmail 연결됨" if gmail_connected else "🟠 Gmail 연결 필요")

        if selected_source == GMAIL_TEST_SOURCE:
            if not demo_mode:
                operation_settings = storage.get_operation_settings()
                agent_enabled = st.toggle(
                    "Agent 실행",
                    value=bool(operation_settings["gmail_auto_sync_enabled"]),
                    help="Gmail 연결 후 기본 실행됩니다. 점검이나 작업 중단이 필요할 때만 일시정지하세요.",
                )
                if agent_enabled != bool(
                    operation_settings["gmail_auto_sync_enabled"]
                ):
                    storage.update_operation_settings(
                        gmail_auto_sync_enabled=agent_enabled,
                        gmail_sync_interval_minutes=int(
                            operation_settings["gmail_sync_interval_minutes"]
                        ),
                    )
                    st.session_state.pop("gmail_auto_sync_last_check", None)
                    st.rerun()
            if "gmail_test_mails" not in st.session_state:
                try:
                    stored_mails = (
                        [] if demo_mode else _load_stored_mail_inputs(storage)
                    )
                    if stored_mails:
                        st.session_state["gmail_test_mails"] = stored_mails
                        st.session_state.setdefault(
                            "gmail_auto_sync_last_check", datetime.now()
                        )
                    else:
                        with st.spinner("제한된 Gmail 테스트 라벨을 확인하고 있습니다..."):
                            st.session_state["gmail_test_mails"] = _load_gmail_test_mails(
                                storage
                            )
                    st.session_state.pop("gmail_load_error", None)
                except Exception as exc:
                    st.session_state["gmail_test_mails"] = []
                    st.session_state["gmail_load_error"] = type(exc).__name__
            gmail_error = st.session_state.get("gmail_load_error")
            if gmail_error:
                st.error(f"Gmail 조회 실패 · {gmail_error}")
            elif demo_mode:
                st.caption(
                    f"가져온 테스트 Mail · "
                    f"{len(st.session_state.get('gmail_test_mails', []))}건"
                )
            if not demo_mode:
                _render_automatic_gmail_sync(storage, settings)
        elif demo_mode:
            st.caption("합성 Mail 15건 · 전체 Agent Core 검증")
        st.divider()
        if demo_mode:
            with st.expander("기술 설정"):
                st.text(f"Endpoint: {settings.api_url}")
                st.text(f"API version: {settings.api_version}")
                st.caption("API 키 값은 화면과 로그에 표시하지 않습니다.")
                st.caption("Outlook/Graph · Post-MVP")
            if st.button("데모 DB 초기화", type="secondary"):
                storage.reset()
                st.session_state.pop("last_result", None)
                st.session_state.pop("demo_flash", None)
                st.rerun()
        else:
            if st.button("MVP 시연·검증 화면", width="stretch"):
                st.session_state["app_mode"] = DEMO_MODE
                st.session_state.pop("selected_mail_source", None)
                st.session_state.pop("gmail_test_mails", None)
                st.rerun()
            st.caption("운영 상세 정보는 ‘운영 상태’에서 확인합니다.")

    gmail_mails = st.session_state.get("gmail_test_mails", [])
    mails = gmail_mails if selected_source == GMAIL_TEST_SOURCE else synthetic_mails
    mail_by_id = {
        mail.mail_id: mail for mail in [*synthetic_mails, *gmail_mails]
    }

    review_flash = st.session_state.pop("review_flash", None)
    if review_flash:
        st.success(review_flash)
    task_edit_flash = st.session_state.pop("task_edit_flash", None)
    if task_edit_flash:
        st.success(task_edit_flash)

    if demo_mode:
        tabs = st.tabs(
            ["업무 현황", "메일 처리함", "확인 필요", "운영 로그", "품질 검증", "데모 도구"]
        )
        with tabs[0]:
            _render_product_dashboard(storage, mails)
        with tabs[1]:
            _render_mailbox(
                storage,
                settings,
                mails,
                selected_source,
                demo_mode=True,
            )
        with tabs[2]:
            st.write("Agent가 확신하지 못한 경우에는 DB 변경을 멈추고 사람의 결정을 기다립니다.")
            _render_review_queue(storage, settings, mail_by_id)
        with tabs[3]:
            _render_event_log(storage, [mail.mail_id for mail in mails])
        with tabs[4]:
            _render_quality_evaluation(settings)
        with tabs[5]:
            st.caption("멘토 시연과 기능 검증용 도구입니다. 실제 업무 화면과 분리했습니다.")
            _render_quick_demo(storage, settings, mail_by_id)
        return

    if operation_page == HOME_PAGE:
        _render_product_dashboard(
            storage,
            mails,
            operation_mode=True,
            mail_source=selected_source,
        )
        return
    if operation_page == TASKS_PAGE:
        st.caption("메일에서 만들어진 업무와 직접 등록한 업무를 한곳에서 관리하고 완료 처리합니다.")
        _render_tasks_and_histories(storage, show_history=False)
        return
    if operation_page == REVIEW_PAGE:
        st.subheader("검토 요청")
        st.write("Agent가 확신하지 못한 변경만 모았습니다. 사용자가 확정하기 전에는 DB를 바꾸지 않습니다.")
        _render_review_queue(storage, settings, mail_by_id)
        return

    if operation_page == AUTOMATION_PAGE:
        _render_automation_center(storage, mails)
        return
    if operation_page == MONITORING_PAGE:
        _render_operations_monitoring(storage, settings, mails, selected_source)
        return
    _render_connection_and_data_settings(storage, gmail_summary)
