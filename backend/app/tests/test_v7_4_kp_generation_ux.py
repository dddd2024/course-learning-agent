"""V7.4-05: Knowledge point generation UX consistency tests.

Tests cover:
1. Warning text in frontend says "归档" (archive), not "删除" (delete)
2. Backend provides a generations history endpoint
3. Generation failure preserves existing active KPs
4. Frontend has a function to fetch generation history
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core import database as db_module
from app.core.security import hash_password
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.user import User


def _get_session():
    return db_module.SessionLocal()


def _auth_client(client: TestClient) -> tuple[int, dict]:
    username = f"testuser_v745_{int(time.time() * 1000) % 100000}"
    resp = client.post("/api/v1/auth/register", json={
        "username": username,
        "password": "test1234",
        "email": f"{username}@test.com",
    })
    assert resp.status_code in (200, 201), resp.text
    resp = client.post("/api/v1/auth/login", json={
        "username": username,
        "password": "test1234",
    })
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    db = _get_session()
    try:
        user = db.query(User).filter(User.username == username).first()
        assert user is not None
        return user.id, {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _make_course_with_material(user_id: int) -> tuple[int, int]:
    """Create a course with a ready material and at least one active chunk."""
    db = _get_session()
    try:
        course = Course(user_id=user_id, name="测试课程", color="#409eff")
        db.add(course)
        db.flush()

        material = Material(
            user_id=user_id,
            course_id=course.id,
            filename="test.pdf",
            file_path="test.pdf",
            file_type="pdf",
            status="ready",
        )
        db.add(material)
        db.flush()

        version = MaterialVersion(
            material_id=material.id,
            version=1,
            status="ready",
            content_hash="abc123",
        )
        db.add(version)
        db.flush()

        chunk = MaterialChunk(
            material_id=material.id,
            material_version_id=version.id,
            course_id=course.id,
            chunk_index=0,
            text="This is a test chunk about important concepts.",
            raw_text="This is a test chunk about important concepts.",
            is_active=1,
            is_indexable=1,
            char_count=45,
            estimated_token_count=12,
            token_count=12,
            stable_key="test:0:abc",
            content_hash="def456",
            keyword_text="test chunk important concepts",
        )
        db.add(chunk)
        db.flush()

        # Create an initial active KP
        kp = KnowledgePoint(
            course_id=course.id,
            user_id=user_id,
            title="初始知识点",
            summary="初始知识点摘要",
            importance=3,
            source_chunk_ids=json.dumps([chunk.id]),
            stable_key=f"{course.id}:initial",
            title_normalized="initial",
            exam_style="理解型",
            review_action="复习教材",
            status="active",
            generation=1,
        )
        db.add(kp)
        db.commit()
        return course.id, chunk.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. Warning text says "归档" not "删除"
# ---------------------------------------------------------------------------

class TestWarningTextConsistency:
    """V7.4-05: Regeneration warning should say '归档' (archive), not '删除' (delete)."""

    def test_outline_view_warning_says_archive(self):
        """OutlineView.vue warning text uses '归档' not '删除'."""
        outline_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "frontend", "src", "views", "OutlineView.vue",
        )
        if not os.path.exists(outline_path):
            pytest.skip("Frontend source not found")
        with open(outline_path, "r", encoding="utf-8") as f:
            content = f.read()
        # The regeneration confirmation message must mention archiving
        assert "归档" in content, (
            "OutlineView regeneration warning must say '归档' (archive) "
            "instead of '删除' (delete) since V6-30 uses generation-based versioning"
        )
        # Must NOT say "删除并替换" (the old misleading text)
        assert "删除并替换" not in content, (
            "OutlineView regeneration warning must not say '删除并替换' — "
            "old KPs are archived, not deleted"
        )


# ---------------------------------------------------------------------------
# 2. Backend generations history endpoint
# ---------------------------------------------------------------------------

class TestGenerationsHistory:
    """V7.4-05: Backend provides a generations history endpoint."""

    def test_generations_endpoint_returns_history(self, client: TestClient):
        """GET /courses/{id}/knowledge-points/generations returns generation history."""
        user_id, headers = _auth_client(client)
        course_id, _ = _make_course_with_material(user_id)

        resp = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points/generations",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        gen = data[0]
        assert "generation" in gen
        assert "status" in gen
        assert "count" in gen
        assert "created_at" in gen

    def test_generations_endpoint_shows_archived(self, client: TestClient):
        """Generations endpoint shows both active and archived generations."""
        user_id, headers = _auth_client(client)
        course_id, chunk_id = _make_course_with_material(user_id)

        # Archive the existing gen-1 KP and create a gen-2 KP
        db = _get_session()
        try:
            db.query(KnowledgePoint).filter(
                KnowledgePoint.course_id == course_id,
                KnowledgePoint.generation == 1,
            ).update({KnowledgePoint.status: "archived"})
            kp2 = KnowledgePoint(
                course_id=course_id,
                user_id=user_id,
                title="第二代知识点",
                summary="第二代摘要",
                importance=3,
                source_chunk_ids=json.dumps([chunk_id]),
                stable_key=f"{course_id}:gen2",
                title_normalized="gen2",
                exam_style="理解型",
                review_action="复习教材",
                status="active",
                generation=2,
            )
            db.add(kp2)
            db.commit()
        finally:
            db.close()

        resp = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points/generations",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should have both gen 1 (archived) and gen 2 (active)
        gens = {g["generation"]: g for g in data}
        assert 1 in gens
        assert 2 in gens
        assert gens[1]["status"] == "archived"
        assert gens[2]["status"] == "active"


# ---------------------------------------------------------------------------
# 3. Generation failure preserves existing KPs
# ---------------------------------------------------------------------------

class TestGenerationFailureSafety:
    """V7.4-05: Generation failure must not clear existing active KPs."""

    def test_failure_preserves_active_kps(self, client: TestClient):
        """When generation fails, existing active KPs remain unchanged."""
        user_id, headers = _auth_client(client)
        course_id, _ = _make_course_with_material(user_id)

        # Count existing KPs before failed generation
        resp_before = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points",
            headers=headers,
        )
        assert resp_before.status_code == 200
        count_before = resp_before.json()["total"]

        # Mock outline_generate to raise an error.
        # The endpoint re-raises, so the TestClient will raise too.
        # We catch it and verify the KPs are still intact afterwards.
        with patch("app.api.v1.endpoints.knowledge_points.outline_generate") as mock_gen:
            mock_gen.side_effect = RuntimeError("LLM service unavailable")
            try:
                client.post(
                    f"/api/v1/courses/{course_id}/knowledge-points/generate",
                    headers=headers,
                )
            except Exception:
                pass  # Expected — the endpoint re-raises

        # Verify existing KPs are still active
        resp_after = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points",
            headers=headers,
        )
        assert resp_after.status_code == 200
        count_after = resp_after.json()["total"]
        assert count_after == count_before, (
            f"Active KP count changed from {count_before} to {count_after} after failure"
        )

    def test_empty_result_preserves_active_kps(self, client: TestClient):
        """When generation produces no valid KPs, existing active KPs remain."""
        user_id, headers = _auth_client(client)
        course_id, _ = _make_course_with_material(user_id)

        resp_before = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points",
            headers=headers,
        )
        count_before = resp_before.json()["total"]

        # Mock outline_generate to return empty list
        with patch("app.api.v1.endpoints.knowledge_points.outline_generate") as mock_gen:
            mock_gen.return_value = []  # No KPs generated
            resp = client.post(
                f"/api/v1/courses/{course_id}/knowledge-points/generate",
                headers=headers,
            )

        # Should fail with 422 (no valid KPs)
        assert resp.status_code == 422

        # Existing KPs must still be active
        resp_after = client.get(
            f"/api/v1/courses/{course_id}/knowledge-points",
            headers=headers,
        )
        count_after = resp_after.json()["total"]
        assert count_after == count_before


# ---------------------------------------------------------------------------
# 4. Frontend has generation history function
# ---------------------------------------------------------------------------

class TestFrontendGenerationHistory:
    """V7.4-05: Frontend API must have a function to fetch generation history."""

    def test_kp_ts_exports_generation_history(self):
        """Frontend API exports a getKPGenerations function."""
        path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "frontend", "src", "api", "knowledge.ts",
        )
        if not os.path.exists(path):
            pytest.skip("Frontend source not found")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "getKPGenerations" in content, (
            "knowledge.ts must export a getKPGenerations function"
        )
        assert "knowledge-points/generations" in content, (
            "getKPGenerations must call the generations endpoint"
        )
