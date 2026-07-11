"""P0 V4 behavior tests for task execution semantics and trusted verification."""
from __future__ import annotations

import json
from datetime import date

from app.models.material import Material
from app.models.knowledge_point import KnowledgePoint
from app.models.plan import StudyGoal, StudyTask
from app.models.quiz import Quiz, QuizItem
from app.services.task_execution_service import start_task, verify_task


def _task(db, user, course, kind, target_type, target_id, spec=None):
    goal = StudyGoal(user_id=user.id, title="V4", deadline=date.today(), daily_minutes=60, status="active")
    db.add(goal); db.flush()
    row = StudyTask(goal_id=goal.id, course_id=course.id, title=f"{kind} target", task_type=kind, estimate_minutes=30, priority=3, status="pending", target_type=target_type, target_id=target_id, target_spec_json=json.dumps(spec or {}))
    db.add(row); db.commit()
    return row


def test_learn_and_review_start_never_change_target_type(db_session, sample_user, sample_course):
    material = Material(user_id=sample_user.id, course_id=sample_course.id, filename="notes.txt", file_type="txt", file_path="x", status="ready")
    point = KnowledgePoint(user_id=sample_user.id, course_id=sample_course.id, title="分页", status="active", source_chunk_ids="[]")
    db_session.add_all([material, point]); db_session.commit()
    learn = _task(db_session, sample_user, sample_course, "learn", "material", material.id)
    review = _task(db_session, sample_user, sample_course, "review", "knowledge_point", point.id)
    assert start_task(db_session, learn.id, sample_user.id)["target_type"] == "material"
    assert start_task(db_session, review.id, sample_user.id)["target_type"] == "knowledge_point"


def test_verify_rejects_client_score_and_reads_submitted_bound_quiz(db_session, sample_user, sample_course):
    quiz = Quiz(user_id=sample_user.id, course_id=sample_course.id, title="真实测验", question_count=2, score=2, status="submitted")
    db_session.add(quiz); db_session.flush()
    db_session.add(QuizItem(quiz_id=quiz.id, question_type="choice", question_text="q", answer="A", order_index=0))
    task = _task(db_session, sample_user, sample_course, "quiz", "quiz", quiz.id, {"pass_score": 60})
    assert verify_task(db_session, task.id, sample_user.id, confirmation=True)["verified"] is True

