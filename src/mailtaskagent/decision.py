from __future__ import annotations

from mailtaskagent.config import Settings
from mailtaskagent.models import (
    ActionProposal,
    AgentAction,
    MailAnalysis,
    MailInput,
    MailIntent,
    TaskCandidate,
    TaskStatus,
)


def decide_action(
    mail: MailInput,
    analysis: MailAnalysis,
    candidates: list[TaskCandidate],
    settings: Settings,
) -> ActionProposal:
    candidate = candidates[0] if len(candidates) == 1 else None

    if analysis.is_task_request and len(candidates) > 1:
        return ActionProposal(
            action=AgentAction.ASK_USER,
            reason=f"관련 활성 Task 후보가 {len(candidates)}개이므로 사용자가 대상을 확정해야 함",
            confidence=min(analysis.confidence, 0.70),
            needs_user_confirmation=True,
        )

    if analysis.confidence < settings.confidence_threshold or analysis.intent == MailIntent.UNCERTAIN:
        return ActionProposal(
            action=AgentAction.ASK_USER,
            target_task_id=candidate.task_id if candidate else None,
            reason=f"신뢰도 또는 의미가 불충분함: {analysis.reason}",
            confidence=analysis.confidence,
            needs_user_confirmation=True,
        )

    lifecycle_intents = {
        MailIntent.DUE_DATE_CHANGE,
        MailIntent.TASK_UPDATE,
        MailIntent.WAITING,
        MailIntent.INFORMATION_RECEIVED,
        MailIntent.COMPLETION,
        MailIntent.CANCELLATION,
    }
    if analysis.intent == MailIntent.NON_TASK or (
        not analysis.is_task_request and analysis.intent not in lifecycle_intents
    ):
        return ActionProposal(
            action=AgentAction.IGNORE,
            reason=analysis.reason,
            confidence=analysis.confidence,
        )

    if analysis.intent == MailIntent.NEW_TASK and candidate is None:
        if not analysis.task_title or not analysis.request_summary:
            raise ValueError("CREATE_TASK requires task_title and request_summary")
        return ActionProposal(
            action=AgentAction.CREATE_TASK,
            task_payload={
                "conversation_id": mail.conversation_id,
                "title": analysis.task_title,
                "requester": analysis.requester,
                "description": analysis.request_summary,
                "due_date": analysis.due_date.isoformat() if analysis.due_date else None,
                "reply_required": analysis.reply_required,
                "status": TaskStatus.TODO.value,
            },
            reason=analysis.reason,
            confidence=analysis.confidence,
        )

    if analysis.intent == MailIntent.DUE_DATE_CHANGE and candidate:
        if analysis.due_date is None:
            return ActionProposal(
                action=AgentAction.ASK_USER,
                target_task_id=candidate.task_id,
                reason="변경 기한을 명확한 날짜로 확정할 수 없음",
                confidence=analysis.confidence,
                needs_user_confirmation=True,
            )
        return ActionProposal(
            action=AgentAction.UPDATE_TASK,
            target_task_id=candidate.task_id,
            changes={"due_date": analysis.due_date.isoformat()},
            reason=analysis.reason,
            confidence=analysis.confidence,
        )

    if analysis.intent == MailIntent.WAITING and candidate:
        return ActionProposal(
            action=AgentAction.SET_WAITING,
            target_task_id=candidate.task_id,
            changes={
                "status": TaskStatus.WAITING_REPLY.value,
                "waiting_since": mail.occurred_at.isoformat(),
            },
            reason=analysis.reason,
            confidence=analysis.confidence,
        )

    if analysis.intent == MailIntent.INFORMATION_RECEIVED and candidate:
        if candidate.status == TaskStatus.WAITING_REPLY:
            return ActionProposal(
                action=AgentAction.UPDATE_TASK,
                target_task_id=candidate.task_id,
                changes={
                    "status": TaskStatus.IN_PROGRESS.value,
                    "waiting_since": None,
                },
                reason=f"대기 중이던 업무에 필요한 정보가 도착함: {analysis.reason}",
                confidence=analysis.confidence,
            )
        return ActionProposal(
            action=AgentAction.LINK_TO_TASK,
            target_task_id=candidate.task_id,
            reason=f"상태 변경 없이 관련 정보를 기존 업무에 연결함: {analysis.reason}",
            confidence=analysis.confidence,
        )

    if analysis.intent == MailIntent.COMPLETION and candidate:
        return ActionProposal(
            action=AgentAction.MARK_COMPLETED,
            target_task_id=candidate.task_id,
            changes={"status": TaskStatus.COMPLETED.value, "waiting_since": None},
            reason=f"완료 근거는 명확하지만 중요 상태 변경이므로 사용자 승인을 요청함: {analysis.reason}",
            confidence=analysis.confidence,
            needs_user_confirmation=True,
        )

    if analysis.intent == MailIntent.CANCELLATION and candidate:
        return ActionProposal(
            action=AgentAction.ASK_USER,
            target_task_id=candidate.task_id,
            changes={"status": TaskStatus.CANCELLED.value, "waiting_since": None},
            reason=f"취소는 중요 상태 변경이므로 사용자 승인을 요청함: {analysis.reason}",
            confidence=analysis.confidence,
            needs_user_confirmation=True,
        )

    if analysis.intent == MailIntent.NEW_TASK and candidate:
        return ActionProposal(
            action=AgentAction.ASK_USER,
            target_task_id=candidate.task_id,
            reason="동일 Thread에 활성 Task가 있어 신규 생성과 기존 업무 연결 중 확인 필요",
            confidence=analysis.confidence,
            needs_user_confirmation=True,
        )

    return ActionProposal(
        action=AgentAction.ASK_USER,
        target_task_id=candidate.task_id if candidate else None,
        reason=f"1단계에서 자동 실행하지 않는 의도: {analysis.intent.value}",
        confidence=analysis.confidence,
        needs_user_confirmation=True,
    )
