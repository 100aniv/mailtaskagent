from __future__ import annotations

from mailtaskagent.config import Settings
from mailtaskagent.models import (
    ActionProposal,
    AgentAction,
    GuardedActionResult,
    GuardVerdict,
    MailAnalysis,
    MailDirection,
    MailInput,
    MailIntent,
    TaskCandidate,
    TaskContextDecision,
    TaskRelation,
    TaskStatus,
)


def decide_action(
    mail: MailInput,
    analysis: MailAnalysis,
    candidates: list[TaskCandidate],
    settings: Settings,
) -> ActionProposal:
    candidate = candidates[0] if len(candidates) == 1 else None
    ambiguous_due_markers = (
        "다음 주 중",
        "이번 주 중",
        "가능한 빨리",
        "조만간",
        "여유될 때",
    )

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

    if (
        analysis.intent == MailIntent.NEW_TASK
        and candidate is None
        and any(marker in f"{mail.subject} {mail.body}" for marker in ambiguous_due_markers)
    ):
        return ActionProposal(
            action=AgentAction.ASK_USER,
            reason="요청은 명확하지만 기한 표현을 단일 날짜로 확정할 수 없음",
            confidence=min(analysis.confidence, 0.70),
            needs_user_confirmation=True,
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
        if candidate.due_date and analysis.due_date < candidate.due_date:
            return ActionProposal(
                action=AgentAction.ASK_USER,
                target_task_id=candidate.task_id,
                changes={"due_date": analysis.due_date.isoformat()},
                reason=(
                    f"기한 단축은 중요 변경이므로 사용자 승인을 요청함: "
                    f"{candidate.due_date.isoformat()} -> {analysis.due_date.isoformat()}"
                ),
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
        if mail.direction != MailDirection.OUTBOUND:
            return ActionProposal(
                action=AgentAction.ASK_USER,
                target_task_id=candidate.task_id,
                reason=(
                    "SET_WAITING은 사용자가 자료나 답변을 요청해 발신한 Mail에만 "
                    "자동 적용함. INBOUND Mail의 WAITING 분석은 사용자 확인 필요"
                ),
                confidence=min(analysis.confidence, 0.70),
                needs_user_confirmation=True,
            )
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

    if analysis.intent == MailIntent.TASK_UPDATE and candidate:
        no_change_markers = ("그대로", "변경 없음", "변경없이", "변경 없이")
        if any(marker in f"{mail.subject} {mail.body}" for marker in no_change_markers):
            return ActionProposal(
                action=AgentAction.LINK_TO_TASK,
                target_task_id=candidate.task_id,
                reason=f"명시적인 필드 변경 없이 기존 요청 유지가 확인됨: {analysis.reason}",
                confidence=analysis.confidence,
            )

        changes = {}
        if analysis.request_summary:
            changes["description"] = analysis.request_summary
        if analysis.reply_required != candidate.reply_required:
            changes["reply_required"] = analysis.reply_required
        if changes:
            return ActionProposal(
                action=AgentAction.UPDATE_TASK,
                target_task_id=candidate.task_id,
                changes=changes,
                reason=analysis.reason,
                confidence=analysis.confidence,
            )
        return ActionProposal(
            action=AgentAction.LINK_TO_TASK,
            target_task_id=candidate.task_id,
            reason=f"변경할 Task 필드가 없어 기존 업무에 Mail만 연결함: {analysis.reason}",
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


def build_guarded_agent_proposal(
    mail: MailInput,
    analysis: MailAnalysis,
    candidates: list[TaskCandidate],
    decision: TaskContextDecision,
    settings: Settings,
) -> GuardedActionResult:
    """Materialize an Agent-selected action and enforce deterministic safety policy."""
    confidence = min(analysis.confidence, decision.confidence)
    candidate = next(
        (
            item
            for item in candidates
            if item.task_id == decision.selected_task_id
        ),
        None,
    )

    def escalate(
        reason: str,
        *,
        target_task_id: str | None = None,
        changes: dict | None = None,
    ) -> GuardedActionResult:
        return GuardedActionResult(
            verdict=GuardVerdict.ESCALATED,
            agent_action=decision.recommended_action,
            final_proposal=ActionProposal(
                action=AgentAction.ASK_USER,
                target_task_id=target_task_id,
                changes=changes or {},
                reason=reason,
                confidence=confidence,
                needs_user_confirmation=True,
            ),
            reason=reason,
        )

    def accept(proposal: ActionProposal, reason: str) -> GuardedActionResult:
        return GuardedActionResult(
            verdict=GuardVerdict.ACCEPTED,
            agent_action=decision.recommended_action,
            final_proposal=proposal,
            reason=reason,
        )

    if analysis.confidence < settings.confidence_threshold or analysis.intent == MailIntent.UNCERTAIN:
        return escalate(
            "Mail 분석 신뢰도 또는 Intent가 불충분하여 Agent Action 자동 실행 차단",
            target_task_id=candidate.task_id if candidate else None,
        )

    if decision.relation == TaskRelation.AMBIGUOUS:
        return escalate(
            f"Task 관계가 모호하여 사용자 확인 필요: {decision.reason}",
            target_task_id=candidate.task_id if candidate else None,
        )

    if decision.recommended_action == AgentAction.ASK_USER:
        changes = {}
        if analysis.intent == MailIntent.CANCELLATION and candidate:
            changes = {"status": TaskStatus.CANCELLED.value, "waiting_since": None}
        elif analysis.intent == MailIntent.DUE_DATE_CHANGE and analysis.due_date and candidate:
            changes = {"due_date": analysis.due_date.isoformat()}
        return escalate(
            f"Agent가 사용자 확인을 제안함: {decision.reason}",
            target_task_id=candidate.task_id if candidate else None,
            changes=changes,
        )

    if decision.relation == TaskRelation.NEW_TASK:
        if decision.selected_task_id is not None:
            return escalate("NEW_TASK 관계가 기존 Task ID를 포함하여 자동 실행 차단")
        if (
            decision.recommended_action != AgentAction.CREATE_TASK
            or analysis.intent != MailIntent.NEW_TASK
            or not analysis.is_task_request
        ):
            return escalate(
                "NEW_TASK 관계와 Mail Intent 또는 Agent Action이 일치하지 않아 자동 생성 차단"
            )
        if not analysis.task_title or not analysis.request_summary:
            return escalate("CREATE_TASK에 필요한 제목 또는 요청 요약이 없어 자동 생성 차단")
        return accept(
            ActionProposal(
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
                reason=decision.reason,
                confidence=confidence,
            ),
            "Agent의 신규 Task 생성 제안과 Mail Intent가 일치하고 필수 Payload 검증 통과",
        )

    if decision.relation != TaskRelation.SAME_TASK:
        return escalate("지원하지 않는 Task 관계로 자동 실행 차단")
    if candidate is None:
        return escalate("선택한 Task가 검색 후보에 존재하지 않아 자동 실행 차단")

    target_task_id = candidate.task_id
    action = decision.recommended_action

    if analysis.intent == MailIntent.DUE_DATE_CHANGE:
        if action != AgentAction.UPDATE_TASK:
            return escalate(
                "기한 변경 Intent와 Agent Action이 일치하지 않아 자동 실행 차단",
                target_task_id=target_task_id,
            )
        if analysis.due_date is None:
            return escalate(
                "변경할 기한을 명확한 날짜로 구성할 수 없어 사용자 확인 필요",
                target_task_id=target_task_id,
            )
        changes = {"due_date": analysis.due_date.isoformat()}
        if candidate.due_date and analysis.due_date < candidate.due_date:
            return escalate(
                (
                    "기한 단축은 중요 변경이므로 사용자 승인 필요: "
                    f"{candidate.due_date.isoformat()} -> {analysis.due_date.isoformat()}"
                ),
                target_task_id=target_task_id,
                changes=changes,
            )
        return accept(
            ActionProposal(
                action=action,
                target_task_id=target_task_id,
                changes=changes,
                reason=decision.reason,
                confidence=confidence,
            ),
            "Agent의 기한 변경 제안과 Payload 검증 통과",
        )

    if analysis.intent == MailIntent.TASK_UPDATE:
        no_change_markers = ("그대로", "변경 없음", "변경없이", "변경 없이")
        changes = {}
        if not any(marker in f"{mail.subject} {mail.body}" for marker in no_change_markers):
            if analysis.request_summary and analysis.request_summary != candidate.description:
                changes["description"] = analysis.request_summary
            if analysis.reply_required != candidate.reply_required:
                changes["reply_required"] = analysis.reply_required
        if action == AgentAction.UPDATE_TASK and changes:
            return accept(
                ActionProposal(
                    action=action,
                    target_task_id=target_task_id,
                    changes=changes,
                    reason=decision.reason,
                    confidence=confidence,
                ),
                "Agent의 Task 변경 제안과 변경 Payload 검증 통과",
            )
        if action == AgentAction.LINK_TO_TASK and not changes:
            return accept(
                ActionProposal(
                    action=action,
                    target_task_id=target_task_id,
                    reason=decision.reason,
                    confidence=confidence,
                ),
                "변경할 필드가 없어 Agent의 Mail 연결 제안 승인",
            )
        return escalate(
            "Task 변경 여부와 Agent Action이 일치하지 않아 자동 실행 차단",
            target_task_id=target_task_id,
            changes=changes,
        )

    if analysis.intent == MailIntent.WAITING:
        if action != AgentAction.SET_WAITING:
            return escalate(
                "회신 대기 Intent와 Agent Action이 일치하지 않아 자동 실행 차단",
                target_task_id=target_task_id,
            )
        if mail.direction != MailDirection.OUTBOUND:
            return escalate(
                "SET_WAITING은 OUTBOUND Mail에만 자동 적용할 수 있어 사용자 확인 필요",
                target_task_id=target_task_id,
            )
        return accept(
            ActionProposal(
                action=action,
                target_task_id=target_task_id,
                changes={
                    "status": TaskStatus.WAITING_REPLY.value,
                    "waiting_since": mail.occurred_at.isoformat(),
                },
                reason=decision.reason,
                confidence=confidence,
            ),
            "Agent의 회신 대기 제안과 OUTBOUND 정책 검증 통과",
        )

    if analysis.intent == MailIntent.INFORMATION_RECEIVED:
        expected_action = (
            AgentAction.UPDATE_TASK
            if candidate.status == TaskStatus.WAITING_REPLY
            else AgentAction.LINK_TO_TASK
        )
        if action != expected_action:
            return escalate(
                "현재 Task 상태와 Agent Action이 일치하지 않아 자동 실행 차단",
                target_task_id=target_task_id,
            )
        changes = (
            {"status": TaskStatus.IN_PROGRESS.value, "waiting_since": None}
            if action == AgentAction.UPDATE_TASK
            else {}
        )
        return accept(
            ActionProposal(
                action=action,
                target_task_id=target_task_id,
                changes=changes,
                reason=decision.reason,
                confidence=confidence,
            ),
            "Agent의 정보 도착 제안과 현재 Task 상태 검증 통과",
        )

    if analysis.intent == MailIntent.COMPLETION:
        if action != AgentAction.MARK_COMPLETED:
            return escalate(
                "완료 Intent와 Agent Action이 일치하지 않아 자동 실행 차단",
                target_task_id=target_task_id,
            )
        reason = "완료는 중요 상태 변경이므로 Agent 제안을 사용자 승인 단계로 이관"
        return GuardedActionResult(
            verdict=GuardVerdict.ESCALATED,
            agent_action=action,
            final_proposal=ActionProposal(
                action=action,
                target_task_id=target_task_id,
                changes={"status": TaskStatus.COMPLETED.value, "waiting_since": None},
                reason=f"{reason}: {decision.reason}",
                confidence=confidence,
                needs_user_confirmation=True,
            ),
            reason=reason,
        )

    if analysis.intent == MailIntent.CANCELLATION:
        return escalate(
            "취소는 중요 상태 변경이므로 사용자 승인 필요",
            target_task_id=target_task_id,
            changes={"status": TaskStatus.CANCELLED.value, "waiting_since": None},
        )

    if analysis.intent == MailIntent.NON_TASK and action == AgentAction.IGNORE:
        return accept(
            ActionProposal(
                action=action,
                reason=decision.reason,
                confidence=confidence,
            ),
            "Agent의 비업무 판단과 Mail Intent 검증 통과",
        )

    return escalate(
        f"Mail Intent {analysis.intent.value}와 Agent Action {action.value}의 안전한 조합이 없음",
        target_task_id=target_task_id,
    )
