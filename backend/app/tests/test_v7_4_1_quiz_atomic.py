"""V7.4.1-04: Quiz submission atomic transaction tests.

Verifies that:
1. Quiz submission with valid task_id updates task status atomically
2. If task update fails, quiz submission rolls back entirely
3. Quiz submission without task_id works normally
4. Quiz status doesn't change to "submitted" if task verification fails
5. Quiz item answers don't persist if the transaction rolls back
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core import database as db_module
from app.models.user import User
from app.models.course import Course
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.knowledge_point import KnowledgePoint
from app.models.quiz import Quiz, QuizItem
from app.models.plan import StudyGoal, StudyTask
from app.core.security import hash_password
from app.tests.conftest import auth_headers


def _auth_client(client: TestClient, username: str = "atomic_user"):
    """Register and return (user_id, headers)."""
    headers = auth_headers(client, username=username, password="test1234")
    user_resp = client.get("/api/v1/auth/me", headers=headers)
    return user_resp.json()["user_id"], headers


def _setup_quiz_with_task(client: TestClient, username: str, task_status: str = "in_progress",
                           target_quiz_id: int | None = None):
    """Create a course, material, KP, quiz, and task. Returns (quiz_id, item_id, task_id, headers)."""
    user_id, headers = _auth_client(client, username)

    # Create course
    resp = client.post("/api/v1/courses", json={"name": f"Atomic-{username}"}, headers=headers)
    course_id = resp.json()["id"]

    # Create material + chunk + KP directly via DB
    db = db_module.SessionLocal()
    try:
        mat = Material(
            user_id=user_id, course_id=course_id, filename="test.pdf",
            file_path="test.pdf", file_type="pdf", status="ready", parse_attempts=0,
        )
        db.add(mat)
        db.flush()
        chunk = MaterialChunk(
            material_id=mat.id, course_id=course_id, chunk_index=0,
            text="测试内容用于生成quiz", is_active=1, is_indexable=1,
        )
        db.add(chunk)
        db.flush()
        kp = KnowledgePoint(
            course_id=course_id, user_id=user_id, title="原子测试知识点",
            summary="测试", importance=5, generation=1, status="active",
            source_chunk_ids=json.dumps([chunk.id]),
        )
        db.add(kp)
        db.flush()
        quiz = Quiz(
            course_id=course_id, user_id=user_id, title="Atomic Test Quiz",
            status="draft", score=0, question_count=1,
        )
        db.add(quiz)
        db.flush()
        item = QuizItem(
            quiz_id=quiz.id, order_index=0,
            question_type="true_false",
            question_text="测试题目",
            options="[]",
            answer="true",
            explanation="测试解释",
            knowledge_point_id=kp.id,
        )
        db.add(item)

        # Create goal and task
        goal = StudyGoal(
            user_id=user_id,
            title="Atomic Goal", deadline=date(2026, 12, 31),
            daily_minutes=30, status="active",
        )
        db.add(goal)
        db.flush()
        actual_target = target_quiz_id if target_quiz_id is not None else quiz.id
        task = StudyTask(
            goal_id=goal.id, course_id=course_id,
            task_type="quiz", target_id=actual_target,
            title="Atomic Task",
            estimate_minutes=30, priority=3,
            execution_status=task_status,
        )
        db.add(task)
        db.commit()
        quiz_id = quiz.id
        item_id = item.id
        task_id = task.id
    finally:
        db.close()

    return quiz_id, item_id, task_id, headers


class TestQuizSubmissionAtomic:
    """V7.4.1-04: Quiz submission and task update must be atomic."""

    def test_submit_with_valid_task_updates_task_atomically(self, client: TestClient):
        """Submitting a quiz with a valid task_id updates both quiz and task in one transaction."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(
            client, "atomic_user1", task_status="in_progress"
        )

        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={
                "answers": [{"item_id": item_id, "user_answer": "true"}],
                "task_id": task_id,
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["score"] == 1
        assert body["total"] == 1

        # Verify both quiz and task were updated
        db = db_module.SessionLocal()
        try:
            q = db.query(Quiz).filter(Quiz.id == quiz_id).first()
            assert q.status == "submitted"
            assert q.score == 1

            t = db.query(StudyTask).filter(StudyTask.id == task_id).first()
            assert t.execution_status == "completed"
        finally:
            db.close()

    def test_submit_with_invalid_task_rolls_back_quiz(self, client: TestClient):
        """If task verification fails, quiz status must NOT change to submitted."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(
            client, "atomic_user2", task_status="completed"  # Already completed
        )

        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={
                "answers": [{"item_id": item_id, "user_answer": "true"}],
                "task_id": task_id,
            },
            headers=headers,
        )
        assert resp.status_code == 409, resp.text

        # Verify quiz was NOT changed
        db = db_module.SessionLocal()
        try:
            q = db.query(Quiz).filter(Quiz.id == quiz_id).first()
            assert q.status == "draft", "Quiz status must remain 'draft' after rollback"
            assert q.score == 0, "Quiz score must remain 0 after rollback"

            # Verify quiz item was NOT changed
            item = db.query(QuizItem).filter(QuizItem.id == item_id).first()
            assert item.user_answer is None or item.user_answer == ""
            assert item.is_correct == 0 or item.is_correct is None
        finally:
            db.close()

    def test_submit_without_task_id_works_normally(self, client: TestClient):
        """Quiz submission without task_id should work normally."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(
            client, "atomic_user3", task_status="in_progress"
        )

        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={
                "answers": [{"item_id": item_id, "user_answer": "true"}],
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["score"] == 1

        db = db_module.SessionLocal()
        try:
            q = db.query(Quiz).filter(Quiz.id == quiz_id).first()
            assert q.status == "submitted"
        finally:
            db.close()

    def test_submit_with_nonexistent_task_rolls_back(self, client: TestClient):
        """Submitting with a task_id that doesn't exist must roll back."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(
            client, "atomic_user4", task_status="in_progress"
        )

        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={
                "answers": [{"item_id": item_id, "user_answer": "true"}],
                "task_id": 99999,  # Nonexistent
            },
            headers=headers,
        )
        assert resp.status_code == 409, resp.text

        db = db_module.SessionLocal()
        try:
            q = db.query(Quiz).filter(Quiz.id == quiz_id).first()
            assert q.status == "draft", "Quiz must remain draft after rollback"
        finally:
            db.close()

    def test_verify_task_failure_does_not_persist_item_answers(self, client: TestClient):
        """If task verification fails, quiz item answers must not persist."""
        # Create a quiz first, then set up a task pointing to a DIFFERENT quiz
        quiz_id, item_id, _, headers = _setup_quiz_with_task(
            client, "atomic_user5", task_status="in_progress"
        )

        # Create another quiz and task pointing to it
        db = db_module.SessionLocal()
        try:
            other_quiz = Quiz(course_id=1, user_id=1, title="Other Quiz", status="draft", score=0)
            db.add(other_quiz)
            db.flush()
            goal = StudyGoal(
                user_id=1,
                title="Mismatch Goal", deadline=date(2026, 12, 31),
                daily_minutes=30, status="active",
            )
            db.add(goal)
            db.flush()
            mismatch_task = StudyTask(
                goal_id=goal.id, course_id=1,
                task_type="quiz", target_id=other_quiz.id,  # Points to different quiz
                title="Mismatched Task",
                estimate_minutes=30, priority=3,
                execution_status="in_progress",
            )
            db.add(mismatch_task)
            db.commit()
            mismatch_task_id = mismatch_task.id
        finally:
            db.close()

        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={
                "answers": [{"item_id": item_id, "user_answer": "true"}],
                "task_id": mismatch_task_id,
            },
            headers=headers,
        )
        assert resp.status_code == 409, resp.text

        db = db_module.SessionLocal()
        try:
            item_db = db.query(QuizItem).filter(QuizItem.id == item_id).first()
            assert not item_db.user_answer, (
                f"Quiz item answer was persisted despite rollback: {item_db.user_answer}"
            )
            assert not item_db.is_correct, (
                f"Quiz item is_correct was persisted despite rollback: {item_db.is_correct}"
            )
        finally:
            db.close()
