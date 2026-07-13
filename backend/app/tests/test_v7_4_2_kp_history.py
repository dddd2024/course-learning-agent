"""V7.4.2-07: Knowledge point generation history.

Tests:
1. GET /{course_id}/knowledge-points/generations/{generation} returns KPs by generation
2. QuizCreationService rejects archived (non-active) generation KPs
3. QuizCreationService accepts only the current active generation
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core import database as db_module
from app.core.security import hash_password
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.user import User
from app.tests.conftest import auth_headers


def _get_session():
    return db_module.SessionLocal()


def _auth_client(client: TestClient, username: str = "v742kp"):
    headers = auth_headers(client, username=username, password="test1234")
    user_resp = client.get("/api/v1/auth/me", headers=headers)
    return user_resp.json()["user_id"], headers


def _make_course(user_id: int, name: str = "KP历史测试课程") -> int:
    db = _get_session()
    try:
        course = Course(user_id=user_id, name=name, color="#409eff")
        db.add(course)
        db.commit()
        db.refresh(course)
        return course.id
    finally:
        db.close()


def _seed_kps_with_generations(course_id: int, user_id: int):
    """Seed knowledge points across two generations.

    Gen 1: 2 active KPs (will be archived)
    Gen 2: 3 active KPs (current)
    """
    db = _get_session()
    try:
        # Generation 1 — archived
        for i in range(2):
            kp = KnowledgePoint(
                course_id=course_id,
                user_id=user_id,
                title=f"Gen1-KP-{i}",
                summary=f"Summary gen1 kp{i}",
                importance=5,
                source_version_ids="[]",
                stable_key=f"{course_id}:gen1kp{i}",
                title_normalized=f"gen1kp{i}",
                status="archived",
                generation=1,
            )
            db.add(kp)

        # Generation 2 — active (current)
        for i in range(3):
            kp = KnowledgePoint(
                course_id=course_id,
                user_id=user_id,
                title=f"Gen2-KP-{i}",
                summary=f"Summary gen2 kp{i}",
                importance=7,
                source_version_ids="[]",
                stable_key=f"{course_id}:gen2kp{i}",
                title_normalized=f"gen2kp{i}",
                status="active",
                generation=2,
            )
            db.add(kp)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. API for reading archived KPs by generation
# ---------------------------------------------------------------------------

class TestKPByGenerationAPI:
    """V7.4.2-07: GET endpoint returns KPs filtered by generation."""

    def test_get_kps_by_generation_1(self, client: TestClient):
        """GET /{course_id}/knowledge-points/generations/1 returns gen 1 KPs."""
        user_id, headers = _auth_client(client, "v742kp_gen1")
        course_id = _make_course(user_id)
        _seed_kps_with_generations(course_id, user_id)

        resp = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points/generations/1",
            headers=headers,
        )
        assert resp.status_code == 200
        kps = resp.json()["items"]
        assert len(kps) == 2
        assert all(kp["generation"] == 1 for kp in kps)

    def test_get_kps_by_generation_2(self, client: TestClient):
        """GET /{course_id}/knowledge-points/generations/2 returns gen 2 KPs."""
        user_id, headers = _auth_client(client, "v742kp_gen2")
        course_id = _make_course(user_id)
        _seed_kps_with_generations(course_id, user_id)

        resp = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points/generations/2",
            headers=headers,
        )
        assert resp.status_code == 200
        kps = resp.json()["items"]
        assert len(kps) == 3
        assert all(kp["generation"] == 2 for kp in kps)

    def test_get_kps_by_nonexistent_generation(self, client: TestClient):
        """GET for a generation that doesn't exist returns empty list."""
        user_id, headers = _auth_client(client, "v742kp_gen3")
        course_id = _make_course(user_id)
        _seed_kps_with_generations(course_id, user_id)

        resp = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points/generations/99",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_generation_kps_include_status_field(self, client: TestClient):
        """KPs returned by generation endpoint include status field."""
        user_id, headers = _auth_client(client, "v742kp_status")
        course_id = _make_course(user_id)
        _seed_kps_with_generations(course_id, user_id)

        resp = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points/generations/1",
            headers=headers,
        )
        kps = resp.json()["items"]
        assert all(kp["status"] == "archived" for kp in kps)


# ---------------------------------------------------------------------------
# 2. QuizCreationService only accepts active generation
# ---------------------------------------------------------------------------

class TestQuizCreationActiveGeneration:
    """V7.4.2-07: QuizCreationService must reject archived generation KPs."""

    def test_rejects_archived_generation_kps(self, client: TestClient):
        """QuizCreationService rejects KPs from an archived generation."""
        user_id, headers = _auth_client(client, "v742kp_quiz_arch")
        course_id = _make_course(user_id)
        _seed_kps_with_generations(course_id, user_id)

        # Get gen 1 (archived) KPs
        resp = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points/generations/1",
            headers=headers,
        )
        archived_kps = resp.json()["items"]
        assert len(archived_kps) == 2

        # Try to create a quiz using archived KPs
        kp_ids = [kp["id"] for kp in archived_kps]
        quiz_resp = client.post(
            "/api/v1/quizzes",
            json={
                "course_id": course_id,
                "knowledge_point_ids": kp_ids,
                "question_count": 3,
            },
            headers=headers,
        )
        assert quiz_resp.status_code in (400, 422), (
            f"Should reject archived KPs. Got {quiz_resp.status_code}: {quiz_resp.text}"
        )

    def test_accepts_active_generation_kps(self, client: TestClient):
        """QuizCreationService accepts KPs from the current active generation."""
        user_id, headers = _auth_client(client, "v742kp_quiz_act")
        course_id = _make_course(user_id)
        _seed_kps_with_generations(course_id, user_id)

        # Get gen 2 (active) KPs
        resp = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points/generations/2",
            headers=headers,
        )
        active_kps = resp.json()["items"]
        assert len(active_kps) == 3

        # Try to create a quiz using active KPs — should not be rejected
        # for generation reasons (may fail for other reasons like LLM)
        kp_ids = [kp["id"] for kp in active_kps]
        quiz_resp = client.post(
            "/api/v1/quizzes",
            json={
                "course_id": course_id,
                "knowledge_point_ids": kp_ids,
                "question_count": 2,
            },
            headers=headers,
        )
        # Should not be 400/422 for generation mismatch
        if quiz_resp.status_code in (400, 422):
            body = quiz_resp.text.lower()
            assert "generation" not in body and "archived" not in body, (
                f"Should not reject active KPs for generation reasons. "
                f"Got {quiz_resp.status_code}: {quiz_resp.text}"
            )

    def test_mixed_generation_kps_rejected(self, client: TestClient):
        """QuizCreationService rejects KPs from mixed generations."""
        user_id, headers = _auth_client(client, "v742kp_quiz_mix")
        course_id = _make_course(user_id)
        _seed_kps_with_generations(course_id, user_id)

        # Get gen 1 (archived) KPs
        resp1 = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points/generations/1",
            headers=headers,
        )
        archived_kps = resp1.json()["items"]

        # Get gen 2 (active) KPs
        resp2 = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points/generations/2",
            headers=headers,
        )
        active_kps = resp2.json()["items"]

        # Mix KPs from both generations
        mixed_ids = [archived_kps[0]["id"], active_kps[0]["id"]]
        quiz_resp = client.post(
            "/api/v1/quizzes",
            json={
                "course_id": course_id,
                "knowledge_point_ids": mixed_ids,
                "question_count": 2,
            },
            headers=headers,
        )
        assert quiz_resp.status_code in (400, 422), (
            f"Should reject mixed generation KPs. Got {quiz_resp.status_code}: {quiz_resp.text}"
        )
