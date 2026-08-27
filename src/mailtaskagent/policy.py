from __future__ import annotations

from mailtaskagent.models import TaskStatus


ALLOWED_STATUS_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.TODO: {
        TaskStatus.TODO,
        TaskStatus.IN_PROGRESS,
        TaskStatus.WAITING_REPLY,
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.IN_PROGRESS: {
        TaskStatus.IN_PROGRESS,
        TaskStatus.WAITING_REPLY,
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_REPLY: {
        TaskStatus.WAITING_REPLY,
        TaskStatus.IN_PROGRESS,
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: {TaskStatus.COMPLETED},
    TaskStatus.CANCELLED: {TaskStatus.CANCELLED},
}


def validate_status_transition(
    current_status: str | TaskStatus,
    next_status: str | TaskStatus,
) -> TaskStatus:
    current = TaskStatus(current_status)
    target = TaskStatus(next_status)
    if target not in ALLOWED_STATUS_TRANSITIONS[current]:
        raise ValueError(
            f"Task status transition is not allowed: {current.value} -> {target.value}"
        )
    return target
