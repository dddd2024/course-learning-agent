"""V7.4.4-04: submitted quizzes are plan execution history."""
from __future__ import annotations

import json
from datetime import date, timedelta

from app.core import database as db_module
from app.models.course import Course
from app.models.plan import MultiCoursePlan, MultiCoursePlanTask, StudyGoal, StudyTask
from app.models.quiz import Quiz
from app.models.user import User
from app.services.multi_plan_history_service import has_execution_history
from app.tests.test_v7_4_2_plan_safety import _make_plan_with_tasks


def _submitted_quiz(db, user_id: int, course_id: int) -> Quiz:
    quiz = Quiz(
        user_id=user_id,
        course_id=course_id,
        title="已提交测验",
        question_count=1,
        status="submitted",
        score=1,
    )
    db.add(quiz)
    db.flush()
    return quiz


def _first_plan_task(db, plan_id: int) -> StudyTask:
    return db.query(StudyTask).join(
        MultiCoursePlanTask, MultiCoursePlanTask.task_id == StudyTask.id,
    ).filter(MultiCoursePlanTask.multi_plan_id == plan_id).first()


def test_pending_quiz_task_with_submitted_target_blocks_delete(client):
    plan_id, headers, user_id = _make_plan_with_tasks(client, "v744_current_quiz", task_status="pending")
    db = db_module.SessionLocal()
    try:
        task = _first_plan_task(db, plan_id)
        task.task_type, task.target_type = "quiz", "quiz"
        quiz = _submitted_quiz(db, user_id, task.course_id)
        task.target_id = quiz.id
        db.commit()
        assert has_execution_history(db, plan_id)
    finally:
        db.close()
    response = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "PLAN_HAS_HISTORY"


def test_history_quiz_id_with_submitted_quiz_blocks_delete(client):
    plan_id, headers, user_id = _make_plan_with_tasks(client, "v744_retry_quiz", task_status="pending")
    db = db_module.SessionLocal()
    try:
        task = _first_plan_task(db, plan_id)
        task.task_type = "quiz"
        task.target_type, task.target_id = "quiz", None
        quiz = _submitted_quiz(db, user_id, task.course_id)
        task.target_spec_json = json.dumps({"history_quiz_ids": [quiz.id]})
        db.commit()
        assert has_execution_history(db, plan_id)
    finally:
        db.close()
    response = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "PLAN_HAS_HISTORY"


def test_other_plan_submitted_quiz_does_not_block_pristine_plan(client):
    plan_id, headers, user_id = _make_plan_with_tasks(client, "v744_other_plan", task_status="pending")
    db = db_module.SessionLocal()
    try:
        pristine_task = _first_plan_task(db, plan_id)
        other_plan = MultiCoursePlan(
            user_id=user_id,
            title="另一份计划",
            deadline=date.today() + timedelta(days=7),
            daily_minutes=30,
            status="active",
        )
        db.add(other_plan)
        goal = StudyGoal(
            user_id=user_id, title="另一份目标", deadline=other_plan.deadline,
            daily_minutes=30, status="active",
        )
        db.add(goal)
        db.flush()
        other_task = StudyTask(
            goal_id=goal.id, course_id=pristine_task.course_id, title="另一份计划测验",
            task_type="quiz", execution_status="pending", target_type="quiz",
        )
        db.add(other_task)
        db.flush()
        quiz = _submitted_quiz(db, user_id, pristine_task.course_id)
        other_task.target_id = quiz.id
        db.add(MultiCoursePlanTask(
            multi_plan_id=other_plan.id, task_id=other_task.id,
            course_id=pristine_task.course_id, estimate_minutes=30,
        ))
        db.commit()
        assert not has_execution_history(db, plan_id)
    finally:
        db.close()
    response = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert response.status_code == 204


def test_other_user_submitted_quiz_id_does_not_block_pristine_plan(client):
    plan_id, headers, _ = _make_plan_with_tasks(client, "v744_other_user", task_status="pending")
    db = db_module.SessionLocal()
    try:
        task = _first_plan_task(db, plan_id)
        foreign_user = User(username="v744_foreign", email="v744_foreign@example.test", password_hash="x")
        db.add(foreign_user)
        db.flush()
        foreign_course = Course(name="Foreign course", user_id=foreign_user.id)
        db.add(foreign_course)
        db.flush()
        foreign_quiz = _submitted_quiz(db, foreign_user.id, foreign_course.id)
        task.task_type, task.target_type, task.target_id = "quiz", "quiz", foreign_quiz.id
        db.commit()
        assert not has_execution_history(db, plan_id)
    finally:
        db.close()
    response = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert response.status_code == 204
