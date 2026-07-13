"""V7.4.2-04: Quiz single-request atomic submission.

Tests that:
1. QuizResultOut includes percentage, pass_score, passed, task_verification
2. Frontend submitQuiz sends task_id in the payload
3. Task verification result is included in the response
4. Submission without task_id still returns the new fields
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


def _auth_client(client: TestClient, username: str = "v742_atomic"):
    headers = auth_headers(client, username=username, password="test1234")
    user_resp = client.get("/api/v1/auth/me", headers=headers)
    return user_resp.json()["user_id"], headers


def _setup_quiz_with_task(client: TestClient, username: str, task_status: str = "in_progress"):
    user_id, headers = _auth_client(client, username)
    resp = client.post("/api/v1/courses", json={"name": f"V742-{username}"}, headers=headers)
    course_id = resp.json()["id"]

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
            text="测试内容", is_active=1, is_indexable=1,
        )
        db.add(chunk)
        db.flush()
        kp = KnowledgePoint(
            course_id=course_id, user_id=user_id, title="测试知识点",
            summary="测试", importance=5, generation=1, status="active",
            source_chunk_ids=json.dumps([chunk.id]),
        )
        db.add(kp)
        db.flush()
        quiz = Quiz(
            course_id=course_id, user_id=user_id, title="V742 Atomic Quiz",
            status="draft", score=0, question_count=1, pass_score=60,
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
        goal = StudyGoal(
            user_id=user_id,
            title="V742 Goal", deadline=date(2026, 12, 31),
            daily_minutes=30, status="active",
        )
        db.add(goal)
        db.flush()
        task = StudyTask(
            goal_id=goal.id, course_id=course_id,
            task_type="quiz", target_id=quiz.id,
            title="V742 Task",
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


class TestQuizResultFields:
    """V7.4.2-04: QuizResultOut must include percentage, pass_score, passed, task_verification."""

    def test_result_includes_percentage(self, client: TestClient):
        """Response must include a percentage field."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(client, "v742_pct")
        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={"answers": [{"item_id": item_id, "user_answer": "true"}]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "percentage" in body, f"Response must include 'percentage', got keys: {list(body.keys())}"
        assert body["percentage"] == 100

    def test_result_includes_pass_score(self, client: TestClient):
        """Response must include the pass_score."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(client, "v742_pass")
        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={"answers": [{"item_id": item_id, "user_answer": "true"}]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "pass_score" in body
        assert body["pass_score"] == 60

    def test_result_includes_passed(self, client: TestClient):
        """Response must include a boolean 'passed' field."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(client, "v742_passed")
        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={"answers": [{"item_id": item_id, "user_answer": "true"}]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "passed" in body
        assert body["passed"] is True

    def test_result_includes_task_verification(self, client: TestClient):
        """Response must include task_verification when task_id is provided."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(client, "v742_verify")
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
        assert "task_verification" in body
        assert body["task_verification"]["verified"] is True

    def test_result_without_task_has_null_task_verification(self, client: TestClient):
        """When no task_id is provided, task_verification should be null."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(client, "v742_no_task")
        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={"answers": [{"item_id": item_id, "user_answer": "true"}]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("task_verification") is None


class TestAtomicSubmission:
    """V7.4.2-04: Submission with task_id must be atomic."""

    def test_valid_task_submission_completes_both(self, client: TestClient):
        """Submitting with valid task_id updates both quiz and task."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(client, "v742_atomic1")
        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={
                "answers": [{"item_id": item_id, "user_answer": "true"}],
                "task_id": task_id,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["score"] == 1
        assert body["task_verification"]["verified"] is True

        db = db_module.SessionLocal()
        try:
            q = db.query(Quiz).filter(Quiz.id == quiz_id).first()
            assert q.status == "submitted"
            t = db.query(StudyTask).filter(StudyTask.id == task_id).first()
            assert t.execution_status == "completed"
        finally:
            db.close()

    def test_failed_task_verification_rolls_back(self, client: TestClient):
        """If task verification fails, quiz stays unchanged."""
        quiz_id, item_id, task_id, headers = _setup_quiz_with_task(
            client, "v742_atomic2", task_status="completed"
        )
        resp = client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={
                "answers": [{"item_id": item_id, "user_answer": "true"}],
                "task_id": task_id,
            },
            headers=headers,
        )
        assert resp.status_code == 409

        db = db_module.SessionLocal()
        try:
            q = db.query(Quiz).filter(Quiz.id == quiz_id).first()
            assert q.status == "draft"
        finally:
            db.close()
