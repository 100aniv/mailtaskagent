from __future__ import annotations

import json
from datetime import date, datetime
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
from mailtaskagent.llm_client import MockMailAnalyzer, build_analyzer
from mailtaskagent.manual_benchmark import (
    calculate_manual_benchmark_result,
    load_manual_benchmark_cases,
    save_manual_benchmark_evidence,
)
from mailtaskagent.models import AgentAction, ReviewDecision
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


def _gmail_connection_summary() -> dict:
    gmail_settings = load_gmail_source_settings()
    return {
        "credentials_ready": gmail_settings.credentials_path.exists(),
        "token_ready": gmail_settings.token_path.exists(),
        "query": gmail_settings.query,
        "max_results": gmail_settings.max_results,
    }


def _load_gmail_test_mails():
    gmail_settings = load_gmail_source_settings()
    source = GmailReadOnlySource(
        build_gmail_service(gmail_settings),
        gmail_settings,
    )
    return source.load()


def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {background: #f6f8fc;}
        .block-container {padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1480px;}
        [data-testid="stSidebar"] {background: #13203b; border-right: 0;}
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label {color: #e7eefc;}
        [data-testid="stSidebar"] button {
            border-color: #415273; color: #e7eefc; background: #1d2d4d;
        }
        [data-testid="stSidebar"] hr {border-color: #334563;}
        [data-testid="stMetric"] {
            background: #ffffff; border: 1px solid #dde5f1; border-radius: 16px;
            padding: 16px 18px; box-shadow: 0 4px 14px rgba(20, 40, 80, 0.04);
        }
        [data-testid="stMetricLabel"] {color: #475569;}
        button[data-baseweb="tab"] {font-weight: 650; padding-left: 14px; padding-right: 14px;}
        button[data-baseweb="tab"][aria-selected="true"] {color: #3157d5;}
        div[data-testid="stStatusWidget"] {border-radius: 14px;}
        .mail-card {
            padding: 16px 18px; border-radius: 14px; background: #ffffff;
            border: 1px solid #dde5f1; margin-bottom: 12px;
        }
        .mail-card small {color: #64748b;}
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


def _task_priority(task: dict) -> tuple[int, str, str]:
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


def _render_product_dashboard(storage, mails) -> None:
    tasks = storage.list_tasks()
    pending_reviews = storage.list_pending_reviews()
    total_mail_count = len(mails)
    processed_count = sum(storage.is_processed(mail.mail_id) for mail in mails)
    active_tasks = [
        task for task in tasks if task["status"] not in {"COMPLETED", "CANCELLED"}
    ]
    attention_tasks = [task for task in active_tasks if _task_attention(task) != "-"]

    st.subheader("오늘의 업무")
    st.caption("메일에서 정리된 업무와 확인이 필요한 변경을 우선순위대로 모았습니다.")
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

    priority_col, attention_col = st.columns([1.7, 1])
    with priority_col:
        st.markdown("### 우선 처리 업무")
        prioritized = sorted(filtered_tasks, key=_task_priority)
        if prioritized:
            priority_frame = pd.DataFrame(
                [
                    {
                        "업무": task["title"],
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
                    st.error(f"시나리오 실행 실패: {exc}")
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


def _process_unprocessed_mails(
    storage,
    settings,
    mails,
    source_batch_name: str = "합성 메일",
) -> None:
    pending_mails = [mail for mail in mails if not storage.is_processed(mail.mail_id)]
    if not pending_mails:
        st.session_state["batch_flash"] = {
            "success": 0,
            "failed": [],
            "message": f"모든 {source_batch_name}이 이미 처리됐습니다.",
        }
        st.rerun()

    workflow = MailTaskWorkflow(settings, storage, build_analyzer(settings))
    progress = st.progress(0, text="메일 자동 정리를 시작합니다.")
    succeeded = 0
    failed = []
    last_result = None
    for index, mail in enumerate(pending_mails, start=1):
        progress.progress(
            index / len(pending_mails),
            text=f"{mail.mail_id} · {mail.subject}",
        )
        try:
            last_result = workflow.process(mail)
            succeeded += 1
        except Exception as exc:
            failed.append({"mail_id": mail.mail_id, "error": str(exc)})
    if last_result:
        st.session_state["last_result"] = last_result.model_dump(mode="json")
    st.session_state["batch_flash"] = {
        "success": succeeded,
        "failed": failed,
        "message": (
            f"미처리 {source_batch_name} {len(pending_mails)}건 자동 정리를 실행했습니다."
        ),
    }
    st.rerun()


def _render_mailbox(storage, settings, mails, source_name: str) -> None:
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
            "사이드바의 새 메일 확인을 실행하세요."
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
    button_label = f"미처리·실패 {source_batch_name} 전체 자동 정리 · {unprocessed_count}건"
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
        selected_button_label = "선택한 메일 재처리" if selected_failed else "선택한 메일 처리"
        if st.button(selected_button_label, width="stretch"):
            try:
                workflow = MailTaskWorkflow(settings, storage, build_analyzer(settings))
                with st.spinner("Mail Context와 현재 Task State를 분석하고 있습니다..."):
                    result = workflow.process(selected)
                st.session_state["last_result"] = result.model_dump(mode="json")
                st.rerun()
            except Exception as exc:
                st.error(f"처리 실패: {exc}")
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
            st.error(f"사용자 결정 반영 실패: {exc}")


def _render_event_log(storage, mail_ids: list[str]) -> None:
    st.subheader("Agent 실행 로그")
    st.caption("M-01~M-05 처리 단계, 성공·실패, 소요 시간과 정제된 상세 정보를 표시합니다.")
    events = storage.list_events()
    if not events:
        st.info("아직 실행 로그가 없습니다.")
        return

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
    st.json(
        {
            "case_id": selected_event["case_id"],
            "message": selected_event["message"],
            "details": _parse_json(selected_event["details_json"]),
            "duration_ms": selected_event["duration_ms"],
            "created_at": selected_event["created_at"],
        }
    )
    st.caption("API Key, Authorization Header, Token과 Secret 값은 저장 전에 제거됩니다.")


def _render_tasks_and_histories(storage) -> None:
    task_col, history_col = st.columns([1, 1.35])
    with task_col:
        st.subheader("현재 Task")
        tasks = storage.list_tasks()
        if tasks:
            task_frame = pd.DataFrame(tasks)
            task_frame["상태"] = task_frame["status"].map(STATUS_LABELS).fillna(task_frame["status"])
            task_frame["주의"] = [_task_attention(task) for task in tasks]
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
            columns = ["Task ID", "업무 제목", "상태", "주의", "기한", "대기 시작", "요청자"]
            st.dataframe(task_frame[columns], width="stretch", hide_index=True)
            with st.expander("Task 직접 수정 · 완료 · 취소"):
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
        st.json(
            {
                "처리 시각": selected_history["created_at"],
                "Source Mail ID": selected_history["mail_id"],
                "Action": selected_history["action"],
                "변경 전": _parse_json(selected_history["before_json"]),
                "변경 후": _parse_json(selected_history["after_json"]),
                "Agent 판단 근거": selected_history["reason"],
                "사용자 결정": _parse_json(selected_history["user_decision"]),
            }
        )


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


def main() -> None:
    st.set_page_config(page_title="MailTaskAgent", page_icon="📬", layout="wide")
    _apply_styles()
    settings = load_settings()
    storage = SQLiteStorage(settings.database_path)
    storage.initialize()
    synthetic_mails = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")
    gmail_summary = _gmail_connection_summary()

    st.title("MailTaskAgent")
    st.write("메일을 업무로 바꾸고, 후속 변경과 확인이 필요한 결정을 놓치지 않게 관리합니다.")

    with st.sidebar:
        st.title("MailTaskAgent")
        st.caption("Personal work copilot")
        st.divider()
        st.subheader("연동 상태")
        if settings.use_mock:
            st.warning("MOCK · 합성 Mail 기능 검증")
        else:
            st.success(f"LIVE · {settings.model}")
        gmail_connected = (
            gmail_summary["credentials_ready"] and gmail_summary["token_ready"]
        )
        source_options = [SYNTHETIC_MAIL_SOURCE]
        if gmail_connected:
            source_options.append(GMAIL_TEST_SOURCE)
        selected_source = st.radio(
            "입력 Source",
            source_options,
            key="selected_mail_source",
        )
        if gmail_connected:
            st.success("Gmail OAuth · 읽기 전용 연결됨")
            st.caption(f"제한 Query · {gmail_summary['query']}")
        elif gmail_summary["credentials_ready"]:
            st.warning("Gmail OAuth · 사용자 승인 필요")
        else:
            st.caption("Gmail OAuth · 선택 연동 전")

        if selected_source == GMAIL_TEST_SOURCE:
            refresh_gmail = st.button(
                "Gmail 새 메일 확인",
                type="secondary",
                width="stretch",
            )
            if refresh_gmail or "gmail_test_mails" not in st.session_state:
                try:
                    with st.spinner("제한된 Gmail 테스트 라벨을 확인하고 있습니다..."):
                        st.session_state["gmail_test_mails"] = _load_gmail_test_mails()
                    st.session_state.pop("gmail_load_error", None)
                except Exception as exc:
                    st.session_state["gmail_test_mails"] = []
                    st.session_state["gmail_load_error"] = type(exc).__name__
            gmail_error = st.session_state.get("gmail_load_error")
            if gmail_error:
                st.error(f"Gmail 조회 실패 · {gmail_error}")
            else:
                st.caption(
                    f"가져온 테스트 Mail · "
                    f"{len(st.session_state.get('gmail_test_mails', []))}건"
                )
        else:
            st.caption("합성 Mail 15건 · 전체 Agent Core 검증")
        st.divider()
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

    dashboard_tab, mailbox_tab, review_tab, log_tab, quality_tab, demo_tab = st.tabs(
        ["업무 현황", "메일 처리함", "확인 필요", "운영 로그", "품질 검증", "데모 도구"]
    )

    with dashboard_tab:
        _render_product_dashboard(storage, mails)

    with mailbox_tab:
        _render_mailbox(storage, settings, mails, selected_source)

    with review_tab:
        st.write("Agent가 확신하지 못한 경우에는 DB 변경을 멈추고 사람의 결정을 기다립니다.")
        _render_review_queue(storage, settings, mail_by_id)

    with log_tab:
        _render_event_log(storage, [mail.mail_id for mail in mails])

    with quality_tab:
        _render_quality_evaluation(settings)

    with demo_tab:
        st.caption("멘토 시연과 기능 검증용 도구입니다. 실제 업무 화면과 분리했습니다.")
        _render_quick_demo(storage, settings, mail_by_id)
