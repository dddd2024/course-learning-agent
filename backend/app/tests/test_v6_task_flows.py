"""V6 task flow tests: learn, review, and quiz task lifecycle.

V7: Learn task flow - page load records target_loaded, then user_confirmed
        event, then verify completes the task.
V7: Review task flow - page load records target_loaded, then review_confirmed
        event, then verify completes the task. Historical KPs are rebound to
        an active stable-key target or rejected.
V6-23: Quiz task flow - start creates quiz, quiz submit auto-verifies on
        pass, low score stays in_progress, retry preserves history.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from app.api.v1.endpoints.quizzes import submit_quiz
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material
from app.models.plan import StudyGoal, StudyTask, TaskExecutionEvent
from app.models.quiz import Quiz, QuizItem
from app.schemas.quiz import QuizSubmit, QuizSubmitAnswer
from app.services.task_execution_service import (
    override_task,
    record_task_event,
    retry_task,
    start_task,
    verify_task,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_goal(db, user, title: str = "V6 Goal") -> StudyGoal:
    goal = StudyGoal(
        user_id=user.id,
        title=title,
        deadline=date.today(),
        daily_minutes=60,
        status="active",
    )
    db.add(goal)
    db.flush()
    return goal


def _make_task(
    db,
    goal,
    course,
    task_type: str,
    target_type: str | None,
    target_id: int | None,
    spec: dict | None = None,
) -> StudyTask:
    task = StudyTask(
        goal_id=goal.id,
        course_id=course.id,
        title=f"{task_type} task",
        task_type=task_type,
        estimate_minutes=30,
        priority=3,
        status="pending",
        target_type=target_type,
        target_id=target_id,
        target_spec_json=json.dumps(spec or {}),
        execution_status="pending",
    )
    db.add(task)
    db.flush()
    return task


def _mock_generate_quiz(**kwargs: Any) -> dict[str, Any]:
    """Return a fixed quiz output with known answers for deterministic tests."""
    knowledge_point_id = kwargs["knowledge_points"][0].id
    difficulty_distribution = kwargs.get("difficulty_distribution") or {"easy": 1, "medium": 1, "hard": 0}
    bands = [
        band
        for band in ("easy", "medium", "hard")
        for _ in range(int(difficulty_distribution.get(band, 0)))
    ]
    items = []
    for index, band in enumerate(bands):
        answer = "B"
        items.append({
            "question_type": "choice",
            "question_text": f"What is {index + 2}+{index + 2}?",
            "options": [
                {"label": "A", "text": str(index + 3), "value": "A"},
                {"label": "B", "text": str((index + 2) * 2), "value": answer},
            ],
            "answer": answer,
            "explanation": "Deterministic fixture answer",
            "knowledge_point_id": knowledge_point_id,
            "difficulty": band,
            "source_evidence": [{"chunk_id": index + 1, "quote_text": "fixture evidence"}],
            "source_evidence_ids": [index + 1],
            "order_index": index,
        })
    return {
        "title": "V6 Test Quiz",
        "items": items,
    }


def _ensure_kp(db, user_id, course_id):
    """Create a knowledge point if none exists, return it."""
    kp = (
        db.query(KnowledgePoint)
        .filter(
            KnowledgePoint.course_id == course_id,
            KnowledgePoint.user_id == user_id,
            KnowledgePoint.status == "active",
        )
        .first()
    )
    if kp is None:
        kp = KnowledgePoint(
            user_id=user_id,
            course_id=course_id,
            title="Test KP",
            summary="Test summary",
            status="active",
            generation=1,
        )
        db.add(kp)
        db.flush()
    return kp


def test_override_uses_state_machine_and_records_event(
    db_session, sample_user, sample_course
):
    goal = _make_goal(db_session, sample_user, title="Override goal")
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="notes.txt",
        file_type="txt",
        file_path="notes.txt",
        status="ready",
    )
    db_session.add(material)
    db_session.flush()
    task = _make_task(
        db_session,
        goal,
        sample_course,
        "learn",
        "material",
        material.id,
        spec={"material_id": material.id},
    )
    start_task(db_session, task.id, sample_user.id)

    result = override_task(db_session, task.id, sample_user.id, "documented exception")

    db_session.refresh(task)
    assert result["todos_completed"] == 0
    assert task.execution_status == "completed"
    assert task.verification_method == "manual_override"
    assert db_session.query(TaskExecutionEvent).filter_by(
        task_id=task.id, event_type="task_override"
    ).count() == 1


def _event_types(db, task_id: int) -> set[str]:
    rows = (
        db.query(TaskExecutionEvent)
        .filter(TaskExecutionEvent.task_id == task_id)
        .all()
    )
    return {row.event_type for row in rows}


# ---------------------------------------------------------------------------
# V6-21: Learn Task Flow
# ---------------------------------------------------------------------------

def test_learn_task_full_flow(db_session, sample_user, sample_course):
    """Learn task: start -> real load -> confirmation -> verify -> completed."""
    # Create a ready material for the learn task target
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="notes.txt",
        file_type="txt",
        file_path="x",
        status="ready",
    )
    db_session.add(material)
    db_session.flush()

    goal = _make_goal(db_session, sample_user)
    task = _make_task(
        db_session,
        goal,
        sample_course,
        "learn",
        "material",
        material.id,
        spec={
            "material_id": material.id,
            "material_version_id": None,
            "chunk_range": [],
            "completion_mode": "loaded_and_confirmed",
        },
    )
    db_session.commit()

    # 1. Start does not claim that the target loaded.
    result = start_task(db_session, task.id, sample_user.id)
    assert result["execution_status"] == "in_progress"

    events = _event_types(db_session, task.id)
    assert "target_loaded" not in events

    # 2. The loaded reader records target_loaded before confirmation.
    record_task_event(db_session, task.id, sample_user.id, event_type="target_loaded", target_id=material.id)
    record_task_event(
        db_session,
        task.id,
        sample_user.id,
        event_type="user_confirmed",
        target_id=material.id,
    )

    # 3. Verify the task
    result = verify_task(db_session, task.id, sample_user.id)
    assert result["verified"] is True

    # 4. Assert task is done and execution is completed
    db_session.refresh(task)
    assert task.status == "done", f"Expected status=done, got {task.status!r}"
    assert task.execution_status == "completed", (
        f"Expected execution_status=completed, got {task.execution_status!r}"
    )


# ---------------------------------------------------------------------------
# V6-22: Review Task Flow
# ---------------------------------------------------------------------------

def test_review_task_full_flow(db_session, sample_user, sample_course):
    """Review task: start -> real load -> review_confirmed -> verify -> completed.

    Also verifies that archived knowledge points do not block task completion.
    """
    # Create an active knowledge point
    kp = KnowledgePoint(
        user_id=sample_user.id,
        course_id=sample_course.id,
        title="进程同步",
        status="active",
        source_chunk_ids="[]",
    )
    db_session.add(kp)
    db_session.flush()

    goal = _make_goal(db_session, sample_user)
    task = _make_task(
        db_session,
        goal,
        sample_course,
        "review",
        "knowledge_point",
        kp.id,
        spec={
            "knowledge_point_id": kp.id,
            "source_chunk_ids": [],
            "review_mode": "loaded_and_confirmed",
        },
    )
    db_session.commit()

    # 1. Start task; the route must separately report a successful load.
    result = start_task(db_session, task.id, sample_user.id)
    assert result["execution_status"] == "in_progress"

    events = _event_types(db_session, task.id)
    assert "target_loaded" not in events

    # 2. Record a successful outline load and then confirmation.
    record_task_event(db_session, task.id, sample_user.id, event_type="target_loaded", target_id=kp.id)
    record_task_event(
        db_session,
        task.id,
        sample_user.id,
        event_type="review_confirmed",
        target_id=kp.id,
    )

    # 3. Verify -> should complete
    result = verify_task(db_session, task.id, sample_user.id)
    assert result["verified"] is True

    db_session.refresh(task)
    assert task.status == "done"
    assert task.execution_status == "completed"

    # --- Archived KP test ---
    # Archive the knowledge point
    kp.status = "archived"
    db_session.commit()

    # Create a new review task targeting the now-archived KP
    goal2 = _make_goal(db_session, sample_user, title="V6 Archived KP Goal")
    task2 = _make_task(
        db_session,
        goal2,
        sample_course,
        "review",
        "knowledge_point",
        kp.id,
        spec={
            "knowledge_point_id": kp.id,
            "source_chunk_ids": [],
            "review_mode": "loaded_and_confirmed",
        },
    )
    db_session.commit()

    # An archived point without a current stable-key replacement must not be
    # accepted as completion evidence.
    from app.core.exceptions import BusinessException
    with pytest.raises(BusinessException) as error:
        start_task(db_session, task2.id, sample_user.id)
    assert error.value.status_code == 422


# ---------------------------------------------------------------------------
# V6-23: Quiz Task Flow
# ---------------------------------------------------------------------------

def test_quiz_task_auto_verify_on_submit(db_session, sample_user, sample_course, monkeypatch):
    """Quiz task: start -> creates quiz -> submit correct answers -> auto-completes.

    Also tests retry: create new quiz, verify old quiz is in history.
    """
    # Mock generate_quiz to return known questions with deterministic answers
    monkeypatch.setattr(
        "app.services.task_execution_service.generate_quiz",
        _mock_generate_quiz,
    )
    monkeypatch.setattr(
        "app.services.quiz_creation_service.generate_quiz",
        _mock_generate_quiz,
    )
    _ensure_kp(db_session, sample_user.id, sample_course.id)

    goal = _make_goal(db_session, sample_user)
    task = _make_task(
        db_session,
        goal,
        sample_course,
        "quiz",
        "quiz",
        None,
        spec={
            "knowledge_point_ids": [],
            "question_count": 2,
            "pass_score": 60,
            "retry_policy": "create_new_quiz",
            "history_quiz_ids": [],
        },
    )
    db_session.commit()

    # 1. Start task -> creates quiz, binds target_id
    result = start_task(db_session, task.id, sample_user.id)
    assert result["quiz_id"] is not None
    quiz_id = result["quiz_id"]
    assert result["target_id"] == quiz_id

    # Get quiz items to construct correct answers
    quiz_items = (
        db_session.query(QuizItem)
        .filter(QuizItem.quiz_id == quiz_id)
        .order_by(QuizItem.order_index.asc())
        .all()
    )
    assert len(quiz_items) == 2

    # 2. Submit quiz with all correct answers + task_id for auto-verify
    correct_answers = [
        QuizSubmitAnswer(item_id=item.id, user_answer=item.answer)
        for item in quiz_items
    ]
    submit_result = submit_quiz(
        quiz_id=quiz_id,
        payload=QuizSubmit(answers=correct_answers, task_id=task.id),
        db=db_session,
        current_user=sample_user,
    )
    assert submit_result.score == 2
    assert submit_result.total == 2

    # 3. Verify task auto-completed (score 100% >= 60% threshold)
    db_session.refresh(task)
    assert task.status == "done", (
        f"Expected status=done after auto-verify, got {task.status!r}"
    )
    assert task.execution_status == "completed", (
        f"Expected execution_status=completed, got {task.execution_status!r}"
    )

    # 4. Test retry: create new quiz, verify old quiz is in history
    retry_result = retry_task(db_session, task.id, sample_user.id)
    new_quiz_id = retry_result["quiz_id"]
    assert new_quiz_id != quiz_id, "Retry should create a new quiz"
    assert quiz_id in retry_result["history_quiz_ids"], (
        "Old quiz id should be preserved in history_quiz_ids"
    )

    db_session.refresh(task)
    assert task.execution_status == "in_progress", (
        f"Expected in_progress after retry, got {task.execution_status!r}"
    )
    assert task.target_id == new_quiz_id


def test_quiz_task_low_score_stays_in_progress(
    db_session, sample_user, sample_course, monkeypatch
):
    """Quiz task with low score (< 60%) should stay in_progress after submit."""
    monkeypatch.setattr(
        "app.services.task_execution_service.generate_quiz",
        _mock_generate_quiz,
    )
    monkeypatch.setattr(
        "app.services.quiz_creation_service.generate_quiz",
        _mock_generate_quiz,
    )
    _ensure_kp(db_session, sample_user.id, sample_course.id)

    goal = _make_goal(db_session, sample_user, title="V6 Low Score Goal")
    task = _make_task(
        db_session,
        goal,
        sample_course,
        "quiz",
        "quiz",
        None,
        spec={
            "knowledge_point_ids": [],
            "question_count": 2,
            "pass_score": 60,
            "retry_policy": "create_new_quiz",
            "history_quiz_ids": [],
        },
    )
    db_session.commit()

    # Start task -> creates quiz
    result = start_task(db_session, task.id, sample_user.id)
    quiz_id = result["quiz_id"]

    quiz_items = (
        db_session.query(QuizItem)
        .filter(QuizItem.quiz_id == quiz_id)
        .order_by(QuizItem.order_index.asc())
        .all()
    )
    assert len(quiz_items) == 2

    # Submit with all wrong answers (score = 0, 0% < 60% threshold)
    wrong_answers = [
        QuizSubmitAnswer(item_id=item.id, user_answer="WRONG_ANSWER")
        for item in quiz_items
    ]
    submit_result = submit_quiz(
        quiz_id=quiz_id,
        payload=QuizSubmit(answers=wrong_answers, task_id=task.id),
        db=db_session,
        current_user=sample_user,
    )
    assert submit_result.score == 0

    # Task should stay in_progress (not completed)
    db_session.refresh(task)
    assert task.execution_status == "in_progress", (
        f"Expected in_progress after low score, got {task.execution_status!r}"
    )
    assert task.status == "pending", (
        f"Expected pending after low score, got {task.status!r}"
    )

    # A failed task has not completed, but it must still be able to create a
    # fresh attempt without reusing the submitted quiz.
    retry_result = retry_task(db_session, task.id, sample_user.id)
    assert retry_result["quiz_id"] != quiz_id
    assert quiz_id in retry_result["history_quiz_ids"]
    db_session.refresh(task)
    assert task.execution_status == "in_progress"
    assert task.target_id == retry_result["quiz_id"]


def test_quiz_submit_rolls_back_when_bound_task_transition_fails(
    db_session, sample_user, sample_course, monkeypatch
):
    """A late task-transition fault must not leave a submitted quiz behind."""
    monkeypatch.setattr(
        "app.services.task_execution_service.generate_quiz", _mock_generate_quiz
    )
    monkeypatch.setattr(
        "app.services.quiz_creation_service.generate_quiz", _mock_generate_quiz
    )
    _ensure_kp(db_session, sample_user.id, sample_course.id)
    goal = _make_goal(db_session, sample_user, title="Atomic submit goal")
    task = _make_task(
        db_session, goal, sample_course, "quiz", "quiz", None,
        spec={"question_count": 2, "pass_score": 60},
    )
    db_session.commit()
    quiz_id = start_task(db_session, task.id, sample_user.id)["quiz_id"]
    items = db_session.query(QuizItem).filter_by(quiz_id=quiz_id).all()

    def fail_transition(*_args, **_kwargs):
        raise RuntimeError("injected task transition failure")

    monkeypatch.setattr(
        "app.api.v1.endpoints.quizzes.verify_task_service", fail_transition
    )
    with pytest.raises(RuntimeError, match="injected task transition failure"):
        submit_quiz(
            quiz_id=quiz_id,
            payload=QuizSubmit(
                task_id=task.id,
                answers=[QuizSubmitAnswer(item_id=item.id, user_answer=item.answer) for item in items],
            ),
            db=db_session,
            current_user=sample_user,
        )

    db_session.expire_all()
    quiz = db_session.get(Quiz, quiz_id)
    task = db_session.get(StudyTask, task.id)
    assert quiz.status == "draft"
    assert quiz.score is None
    assert all(item.user_answer is None and item.is_correct is None for item in quiz.items)
    assert task.execution_status == "in_progress"
