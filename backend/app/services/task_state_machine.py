"""Unified task state machine.

``transition_task`` is the single authority that mutates a
``StudyTask``'s lifecycle state. Every action writes a
``TaskExecutionEvent`` audit record and commits in one transaction so
the state change and its trail are atomic.

State diagram (mirrored on ``StudyTask.execution_status``)::

    pending --start--> in_progress --complete/verify(pass)/override--> completed
                              ^                                         |
                              |                                      retry
                              |                                         |
                              +-----------------------------------------+
                                            (retry: completed -> in_progress)

    completed --reopen--> pending      (resets todos + goal -> active)
    any      --cancel--> cancelled     (terminal, no further transitions)

Mandatory invariants enforced here:

1. Completing a task auto-completes its associated Todos.
2. Reopening a task resets its associated Todos to pending.
3. When every task of a goal is completed the goal becomes ``done``.
4. Reopening any task forces the goal back to ``active``.
5. Todos linked to a task cannot bypass task verification to complete
   (use ``todo_update_allowed`` from ``plan_state_service``).
6. A goal cannot be marked done while tasks remain incomplete
   (see ``mark_goal_done``), unless ``override=True``.
7. Every transition writes a ``TaskExecutionEvent`` record.
8. Each call commits exactly once at the end (single transaction).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.plan import StudyGoal, StudyTask, TaskExecutionEvent, Todo
from app.services.plan_state_service import recompute_goal

# Actions accepted by ``transition_task``.
VALID_ACTIONS = frozenset(
    {
        "start",
        "record_event",
        "verify",
        "complete",
        "retry",
        "override",
        "reopen",
        "cancel",
    }
)

# A task in this state cannot transition to anything else.
TERMINAL_STATE = "cancelled"

# Completion-like states used by goal recomputation.
_DONE_STATES = frozenset({"done", "completed"})


def _record_event(
    db: Session,
    task: StudyTask,
    user_id: int,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> TaskExecutionEvent:
    """Append a ``TaskExecutionEvent`` row (not yet committed)."""
    event = TaskExecutionEvent(
        task_id=task.id,
        user_id=user_id,
        event_type=event_type,
        target_type=task.target_type,
        target_id=task.target_id,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
        occurred_at=datetime.now(),
    )
    db.add(event)
    db.flush()  # assign a primary key so callers can read ``event.id``
    return event


def _complete_todos(db: Session, task: StudyTask, now: datetime) -> int:
    """Mark every Todo linked to ``task`` as completed. Returns count."""
    count = 0
    for todo in db.query(Todo).filter(Todo.task_id == task.id).all():
        todo.status = "completed"
        todo.completed_at = now
        count += 1
    return count


def _reset_todos(db: Session, task: StudyTask) -> int:
    """Reset every Todo linked to ``task`` back to pending. Returns count."""
    count = 0
    for todo in db.query(Todo).filter(Todo.task_id == task.id).all():
        todo.status = "pending"
        todo.completed_at = None
        count += 1
    return count


def _goal_status(db: Session, goal_id: int) -> str | None:
    goal = db.query(StudyGoal).filter(StudyGoal.id == goal_id).first()
    return goal.status if goal is not None else None


def _ensure_started(db: Session, task: StudyTask) -> None:
    """Force a task into the in_progress state without writing an event.

    Used by ``retry`` so the task is in_progress before the retry event is
    recorded, keeping a single event per call.
    """
    now = datetime.now()
    if task.started_at is None:
        task.started_at = now
    task.execution_status = "in_progress"
    task.status = "pending"
    task.completed_at = None
    task.auto_completed_at = None
    task.manual_completed_at = None
    task.last_action_at = now


def transition_task(
    db: Session,
    task: StudyTask,
    action: str,
    actor_user_id: int,
    evidence: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Unified state transition for a ``StudyTask``.

    Parameters
    ----------
    db:
        Active SQLAlchemy session. The function commits exactly once at the
        end (single transaction, invariant 8).
    task:
        The ``StudyTask`` row to transition. The object is mutated in place.
    action:
        One of ``start, record_event, verify, complete, retry, override,
        reopen, cancel``.
    actor_user_id:
        The user performing the action (recorded on the audit event).
    evidence:
        Optional payload. For ``verify`` a ``{"passed": bool}`` key drives
        pass/fail. For ``record_event`` it is stored verbatim and an optional
        ``event_type`` key overrides the default event type.
    reason:
        Mandatory for ``override``; optional human note for other actions.

    Returns
    -------
    dict
        ``{"action", "previous_status", "new_status", "task_status",
        "events_created", "todos_affected", "goal_status"}``.

    Raises
    ------
    ValueError
        On any invalid transition (see module docstring) or when ``override``
        is invoked without a ``reason``.
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"未知动作: {action!r}")

    previous_state = task.execution_status

    # Invariant: cancelled is terminal -- no action may leave it.
    if previous_state == TERMINAL_STATE:
        raise ValueError(
            f"任务已取消，无法执行动作 {action!r}（cancelled 为终态）"
        )

    now = datetime.now()
    events_created: list[str] = []
    todos_affected = 0

    if action == "start":
        if previous_state != "pending":
            raise ValueError(
                f"start 仅允许从 pending 开始，当前状态: {previous_state!r}"
            )
        if task.started_at is None:
            task.started_at = now
        task.execution_status = "in_progress"
        task.status = "pending"
        task.last_action_at = now
        ev = _record_event(
            db, task, actor_user_id, "task_started",
            {"from": previous_state, "to": "in_progress", "reason": reason},
        )
        events_created.append(ev.event_type)

    elif action == "record_event":
        # No state change -- purely an audit record.
        event_type = (evidence or {}).get("event_type", "record_event")
        ev = _record_event(
            db, task, actor_user_id, event_type, evidence or {},
        )
        events_created.append(ev.event_type)
        task.last_action_at = now

    elif action == "verify":
        if previous_state != "in_progress":
            raise ValueError(
                f"verify 仅允许从 in_progress 进行，当前状态: {previous_state!r}"
            )
        passed = bool((evidence or {}).get("passed", True))
        if passed:
            task.execution_status = "completed"
            task.status = "done"
            task.completed_at = now
            task.auto_completed_at = now
            todos_affected = _complete_todos(db, task, now)
            recompute_goal(db, task.goal_id)
            ev = _record_event(
                db, task, actor_user_id, "task_verified",
                {
                    "from": previous_state, "to": "completed",
                    "passed": True, "evidence": evidence or {},
                },
            )
            events_created.append(ev.event_type)
        else:
            # Failed verification: stay in_progress.
            task.last_action_at = now
            ev = _record_event(
                db, task, actor_user_id, "task_verify_failed",
                {
                    "from": previous_state, "to": "in_progress",
                    "passed": False, "evidence": evidence or {},
                },
            )
            events_created.append(ev.event_type)

    elif action == "complete":
        if previous_state != "in_progress":
            raise ValueError(
                f"complete 仅允许从 in_progress 完成，当前状态: {previous_state!r}"
            )
        task.execution_status = "completed"
        task.status = "done"
        task.completed_at = now
        task.auto_completed_at = now
        todos_affected = _complete_todos(db, task, now)
        recompute_goal(db, task.goal_id)
        ev = _record_event(
            db, task, actor_user_id, "task_completed",
            {"from": previous_state, "to": "completed", "reason": reason},
        )
        events_created.append(ev.event_type)

    elif action == "retry":
        if previous_state != "completed":
            raise ValueError(
                f"retry 仅允许从 completed 重试，当前状态: {previous_state!r}"
            )
        # Preserve quiz history inside target_spec_json (does not generate a
        # new quiz here -- that side-effect belongs to the execution service).
        spec: dict[str, Any] = {}
        if task.target_spec_json:
            try:
                parsed = json.loads(task.target_spec_json)
                if isinstance(parsed, dict):
                    spec = parsed
            except (json.JSONDecodeError, TypeError):
                spec = {}
        if task.task_type == "quiz" and task.target_id is not None:
            history = list(spec.get("history_quiz_ids") or [])
            if task.target_id not in history:
                history.append(task.target_id)
            spec["history_quiz_ids"] = history
            task.target_spec_json = json.dumps(spec, ensure_ascii=False)

        _ensure_started(db, task)
        recompute_goal(db, task.goal_id)
        ev = _record_event(
            db, task, actor_user_id, "task_retry",
            {
                "from": previous_state, "to": "in_progress",
                "history_quiz_ids": spec.get("history_quiz_ids", []),
                "reason": reason,
            },
        )
        events_created.append(ev.event_type)

    elif action == "override":
        if not reason:
            raise ValueError("override 必须提供 reason")
        task.execution_status = "completed"
        task.status = "done"
        task.completed_at = now
        task.manual_completed_at = now
        task.auto_completed_at = None
        todos_affected = _complete_todos(db, task, now)
        recompute_goal(db, task.goal_id)
        ev = _record_event(
            db, task, actor_user_id, "task_override",
            {
                "from": previous_state, "to": "completed",
                "reason": reason, "actor": actor_user_id,
            },
        )
        events_created.append(ev.event_type)

    elif action == "reopen":
        if previous_state != "completed":
            raise ValueError(
                f"reopen 仅允许从 completed 重开，当前状态: {previous_state!r}"
            )
        task.execution_status = "pending"
        task.status = "pending"
        task.started_at = None
        task.completed_at = None
        task.auto_completed_at = None
        task.manual_completed_at = None
        task.last_action_at = now
        todos_affected = _reset_todos(db, task)
        # Invariant 4: any reopened task forces the goal back to active.
        recompute_goal(db, task.goal_id)
        ev = _record_event(
            db, task, actor_user_id, "task_reopened",
            {
                "from": previous_state, "to": "pending",
                "todos_reset": todos_affected, "reason": reason,
            },
        )
        events_created.append(ev.event_type)

    elif action == "cancel":
        task.execution_status = TERMINAL_STATE
        task.status = TERMINAL_STATE
        task.last_action_at = now
        ev = _record_event(
            db, task, actor_user_id, "task_cancelled",
            {"from": previous_state, "to": TERMINAL_STATE, "reason": reason},
        )
        events_created.append(ev.event_type)

    # Invariant 8: single commit at the end.
    db.commit()
    db.refresh(task)

    return {
        "action": action,
        "previous_status": previous_state,
        "new_status": task.execution_status,
        "task_status": task.status,
        "events_created": events_created,
        "todos_affected": todos_affected,
        "goal_status": _goal_status(db, task.goal_id),
    }


def mark_goal_done(
    db: Session,
    goal: StudyGoal,
    *,
    override: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    """Mark a ``StudyGoal`` as done, enforcing invariant 6.

    Raises ``ValueError`` if any task under the goal is not yet completed
    (unless ``override=True``). The goal status is otherwise set automatically
    by ``recompute_goal`` during task completion, so this function is the
    guarded manual entry-point.
    """
    tasks = (
        db.query(StudyTask)
        .filter(StudyTask.goal_id == goal.id)
        .all()
    )
    incomplete = [
        t for t in tasks
        if t.execution_status not in {"completed", TERMINAL_STATE}
    ]
    if incomplete and not override:
        raise ValueError(
            f"目标尚有 {len(incomplete)} 个未完成任务，无法标记为完成"
        )
    goal.status = "done"
    db.commit()
    db.refresh(goal)
    return {
        "goal_id": goal.id,
        "goal_status": goal.status,
        "incomplete_count": len(incomplete),
        "override": override,
        "reason": reason,
    }


__all__ = [
    "VALID_ACTIONS",
    "TERMINAL_STATE",
    "transition_task",
    "mark_goal_done",
]
