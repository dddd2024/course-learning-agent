"""V6 unified task state-machine tests.

Covers ``transition_task`` in ``app.services.task_state_machine``: every
supported action, the mandatory invariants (todo auto-complete/reopen,
goal auto-done/active), invalid-transition rejection, and the audit
``TaskExecutionEvent`` trail.

Rows are created directly via the ``db_session`` fixture so no HTTP /
quiz-generation machinery is required.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.models.plan import StudyGoal, StudyTask, TaskExecutionEvent, Todo
from app.services.task_state_machine import (
    TERMINAL_STATE,
    mark_goal_done,
    transition_task,
)


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

def _make_goal(db, user, *, status="active", title="G"):
    goal = StudyGoal(
        user_id=user.id,
        title=title,
        deadline=date.today(),
        daily_minutes=30,
        status=status,
    )
    db.add(goal)
    db.flush()
    return goal


def _make_task(
    db,
    goal,
    course,
    *,
    task_type="learn",
    execution_status="pending",
    status="pending",
    target_type=None,
    target_id=None,
    title="T",
):
    task = StudyTask(
        goal_id=goal.id,
        course_id=course.id,
        title=title,
        task_type=task_type,
        estimate_minutes=30,
        priority=3,
        status=status,
        target_type=target_type,
        target_id=target_id,
        execution_status=execution_status,
    )
    db.add(task)
    db.flush()
    return task


def _make_todo(db, user, task, course, *, status="pending"):
    todo = Todo(
        user_id=user.id,
        task_id=task.id,
        course_id=course.id,
        title="todo",
        scheduled_date=date.today(),
        estimate_minutes=15,
        status=status,
    )
    db.add(todo)
    db.flush()
    return todo


def _events_for(db, task):
    return (
        db.query(TaskExecutionEvent)
        .filter(TaskExecutionEvent.task_id == task.id)
        .all()
    )


# ---------------------------------------------------------------------------
# 1. start
# ---------------------------------------------------------------------------

def test_start_action_pending_to_in_progress(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(db_session, goal, sample_course)

    result = transition_task(db_session, task, "start", sample_user.id)

    assert result["previous_status"] == "pending"
    assert result["new_status"] == "in_progress"
    assert task.execution_status == "in_progress"
    assert task.started_at is not None
    assert task.last_action_at is not None
    # An audit event was written.
    events = _events_for(db_session, task)
    assert len(events) == 1
    assert events[0].event_type == "task_started"


# ---------------------------------------------------------------------------
# 2. complete
# ---------------------------------------------------------------------------

def test_complete_action_in_progress_to_completed(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(db_session, goal, sample_course, execution_status="in_progress")
    _make_todo(db_session, sample_user, task, sample_course)

    result = transition_task(db_session, task, "complete", sample_user.id)

    assert result["new_status"] == "completed"
    assert task.execution_status == "completed"
    assert task.status == "done"
    assert task.completed_at is not None
    assert result["todos_affected"] == 1
    events = _events_for(db_session, task)
    assert len(events) == 1
    assert events[0].event_type == "task_completed"


# ---------------------------------------------------------------------------
# 3. reopen
# ---------------------------------------------------------------------------

def test_reopen_action_completed_to_pending(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user, status="done")
    task = _make_task(
        db_session, goal, sample_course,
        execution_status="completed", status="done",
    )
    task.completed_at = task.started_at = task.auto_completed_at = task.manual_completed_at = None
    db_session.flush()
    _make_todo(db_session, sample_user, task, sample_course, status="completed")

    result = transition_task(db_session, task, "reopen", sample_user.id)

    assert result["new_status"] == "pending"
    assert task.execution_status == "pending"
    assert task.status == "pending"
    assert task.completed_at is None
    assert task.started_at is None
    assert result["todos_affected"] == 1
    assert result["goal_status"] == "active"
    events = _events_for(db_session, task)
    assert len(events) == 1
    assert events[0].event_type == "task_reopened"


# ---------------------------------------------------------------------------
# 4. cancel
# ---------------------------------------------------------------------------

def test_cancel_action_to_cancelled(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(db_session, goal, sample_course, execution_status="in_progress")

    result = transition_task(db_session, task, "cancel", sample_user.id)

    assert result["new_status"] == "cancelled"
    assert task.execution_status == "cancelled"
    events = _events_for(db_session, task)
    assert len(events) == 1
    assert events[0].event_type == "task_cancelled"

    # Cancelled is terminal -- no further action is allowed.
    with pytest.raises(ValueError):
        transition_task(db_session, task, "start", sample_user.id)


# ---------------------------------------------------------------------------
# 5. override requires reason
# ---------------------------------------------------------------------------

def test_override_action_requires_reason(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(db_session, goal, sample_course, execution_status="in_progress")

    with pytest.raises(ValueError):
        transition_task(db_session, task, "override", sample_user.id)


# ---------------------------------------------------------------------------
# 6. override sets manual_completed_at
# ---------------------------------------------------------------------------

def test_override_sets_manual_completed_at(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(db_session, goal, sample_course, execution_status="in_progress")
    _make_todo(db_session, sample_user, task, sample_course)

    result = transition_task(
        db_session, task, "override", sample_user.id, reason="manual"
    )

    assert result["new_status"] == "completed"
    assert task.manual_completed_at is not None
    assert task.auto_completed_at is None
    assert task.status == "done"
    events = _events_for(db_session, task)
    assert len(events) == 1
    assert events[0].event_type == "task_override"


# ---------------------------------------------------------------------------
# 7. retry
# ---------------------------------------------------------------------------

def test_retry_completed_to_in_progress(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(
        db_session, goal, sample_course,
        task_type="quiz", target_type="quiz", target_id=42,
        execution_status="completed", status="done",
    )
    task.completed_at = task.started_at = None
    db_session.flush()

    result = transition_task(db_session, task, "retry", sample_user.id)

    assert result["new_status"] == "in_progress"
    assert task.execution_status == "in_progress"
    # History is preserved inside target_spec_json.
    import json
    spec = json.loads(task.target_spec_json)
    assert 42 in spec["history_quiz_ids"]
    # A retry event was written.
    events = _events_for(db_session, task)
    assert len(events) == 1
    assert events[0].event_type == "task_retry"


# ---------------------------------------------------------------------------
# 8. complete auto-completes todos
# ---------------------------------------------------------------------------

def test_complete_auto_completes_todos(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(db_session, goal, sample_course, execution_status="in_progress")
    todo_a = _make_todo(db_session, sample_user, task, sample_course, status="pending")
    todo_b = _make_todo(db_session, sample_user, task, sample_course, status="pending")

    transition_task(db_session, task, "complete", sample_user.id)

    db_session.refresh(todo_a)
    db_session.refresh(todo_b)
    assert todo_a.status == "completed"
    assert todo_a.completed_at is not None
    assert todo_b.status == "completed"


# ---------------------------------------------------------------------------
# 9. reopen resets todos to pending
# ---------------------------------------------------------------------------

def test_reopen_resets_todos_to_pending(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(
        db_session, goal, sample_course,
        execution_status="completed", status="done",
    )
    todo = _make_todo(db_session, sample_user, task, sample_course, status="completed")
    todo.completed_at = date.today()
    db_session.flush()

    transition_task(db_session, task, "reopen", sample_user.id)

    db_session.refresh(todo)
    assert todo.status == "pending"
    assert todo.completed_at is None


# ---------------------------------------------------------------------------
# 10. all tasks done -> goal auto-done
# ---------------------------------------------------------------------------

def test_all_tasks_done_goal_auto_done(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user, status="active")
    t1 = _make_task(db_session, goal, sample_course, execution_status="in_progress")
    t2 = _make_task(db_session, goal, sample_course, execution_status="in_progress")

    transition_task(db_session, t1, "complete", sample_user.id)
    result = transition_task(db_session, t2, "complete", sample_user.id)

    assert result["goal_status"] == "done"
    db_session.refresh(goal)
    assert goal.status == "done"


# ---------------------------------------------------------------------------
# 11. any task reopened -> goal active
# ---------------------------------------------------------------------------

def test_any_task_reopened_goal_active(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user, status="done")
    t1 = _make_task(
        db_session, goal, sample_course,
        execution_status="completed", status="done",
    )
    t2 = _make_task(
        db_session, goal, sample_course,
        execution_status="completed", status="done",
    )
    for t in (t1, t2):
        t.completed_at = t.started_at = None
    db_session.flush()

    result = transition_task(db_session, t1, "reopen", sample_user.id)

    assert result["goal_status"] == "active"
    db_session.refresh(goal)
    assert goal.status == "active"


# ---------------------------------------------------------------------------
# 12. goal cannot be done with incomplete tasks
# ---------------------------------------------------------------------------

def test_goal_cannot_done_with_incomplete_tasks(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user, status="active")
    _make_task(db_session, goal, sample_course, execution_status="pending")
    _make_task(db_session, goal, sample_course, execution_status="completed", status="done")

    with pytest.raises(ValueError):
        mark_goal_done(db_session, goal)


# ---------------------------------------------------------------------------
# 13. every transition writes an event
# ---------------------------------------------------------------------------

def test_every_transition_writes_event(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(db_session, goal, sample_course)

    transition_task(db_session, task, "start", sample_user.id)
    transition_task(db_session, task, "record_event", sample_user.id,
                    evidence={"event_type": "target_loaded"})
    transition_task(db_session, task, "complete", sample_user.id)

    types = [e.event_type for e in _events_for(db_session, task)]
    assert types == ["task_started", "target_loaded", "task_completed"]


# ---------------------------------------------------------------------------
# 14. invalid: completed -> in_progress via start
# ---------------------------------------------------------------------------

def test_invalid_transition_completed_to_in_progress(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(
        db_session, goal, sample_course,
        execution_status="completed", status="done",
    )

    # `start` is pending -> in_progress only; calling it on a completed
    # task is an invalid completed -> in_progress transition.
    with pytest.raises(ValueError):
        transition_task(db_session, task, "start", sample_user.id)


# ---------------------------------------------------------------------------
# 15. invalid: pending -> completed (without start)
# ---------------------------------------------------------------------------

def test_invalid_transition_pending_to_completed(db_session, sample_user, sample_course):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(db_session, goal, sample_course, execution_status="pending")

    with pytest.raises(ValueError):
        transition_task(db_session, task, "complete", sample_user.id)


# ---------------------------------------------------------------------------
# 16. parametrized state transitions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "from_status, action, expected_status, expect_raise",
    [
        ("pending", "start", "in_progress", False),
        ("in_progress", "complete", "completed", False),
        ("in_progress", "verify", "completed", False),  # default evidence passes
        ("in_progress", "override", "completed", False),
        ("in_progress", "cancel", TERMINAL_STATE, False),
        ("completed", "reopen", "pending", False),
        ("completed", "retry", "in_progress", False),
        # invalid transitions
        ("pending", "complete", None, True),
        ("completed", "start", None, True),
        ("cancelled", "start", None, True),
    ],
)
def test_parametrized_state_transitions(
    db_session, sample_user, sample_course,
    from_status, action, expected_status, expect_raise,
):
    goal = _make_goal(db_session, sample_user)
    task = _make_task(
        db_session, goal, sample_course,
        execution_status=from_status,
        status="done" if from_status == "completed" else from_status,
        task_type="quiz" if action == "retry" else "learn",
        target_type="quiz" if action == "retry" else None,
        target_id=99 if action == "retry" else None,
    )
    if from_status == "completed":
        task.completed_at = task.started_at = None
    db_session.flush()

    if expect_raise:
        with pytest.raises(ValueError):
            transition_task(
                db_session, task, action, sample_user.id,
                reason="r" if action == "override" else None,
                evidence={"passed": True} if action == "verify" else None,
            )
        return

    result = transition_task(
        db_session, task, action, sample_user.id,
        reason="r" if action == "override" else None,
        evidence={"passed": True} if action == "verify" else None,
    )
    assert result["new_status"] == expected_status
    assert result["events_created"], "every transition must write an event"
