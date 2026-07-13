"""V7.4.2-05: Multi-course plan history safety and archiving.

Tests that:
1. force=true is removed (or rejected) from DELETE endpoint
2. POST /plans/multi/{id}/archive endpoint exists
3. Plans with execution history cannot be deleted (only archived)
4. Plans without execution history can be deleted
5. Archived plans have status "archived"
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core import database as db_module
from app.models.plan import StudyGoal, StudyTask, MultiCoursePlan, MultiCoursePlanTask
from app.models.course import Course
from app.tests.conftest import auth_headers


def _auth_client(client: TestClient, username: str = "v742_plan"):
    headers = auth_headers(client, username=username, password="test1234")
    user_resp = client.get("/api/v1/auth/me", headers=headers)
    return user_resp.json()["user_id"], headers


def _make_plan_with_tasks(client: TestClient, username: str, task_status: str = "pending"):
    """Create a multi-course plan with tasks.

    Creates the plan parent via API (which may produce zero tasks if the
    LLM planner is unavailable in tests), then directly inserts
    StudyGoal + StudyTask + MultiCoursePlanTask rows via DB so we have
    deterministic tasks to test against.
    """
    user_id, headers = _auth_client(client, username)

    # Create two courses
    resp1 = client.post("/api/v1/courses", json={"name": f"Course-A-{username}"}, headers=headers)
    course_a = resp1.json()["id"]
    resp2 = client.post("/api/v1/courses", json={"name": f"Course-B-{username}"}, headers=headers)
    course_b = resp2.json()["id"]

    # Create materials for each course (required for plan creation)
    db = db_module.SessionLocal()
    try:
        from app.models.material import Material
        from app.models.material_chunk import MaterialChunk
        for cid in [course_a, course_b]:
            mat = Material(
                user_id=user_id, course_id=cid, filename="test.pdf",
                file_path="test.pdf", file_type="pdf", status="ready", parse_attempts=0,
            )
            db.add(mat)
            db.flush()
            chunk = MaterialChunk(
                material_id=mat.id, course_id=cid, chunk_index=0,
                text="content", is_active=1, is_indexable=1,
            )
            db.add(chunk)
        db.commit()
    finally:
        db.close()

    # Create multi-course plan via API
    today = date.today()
    plan_payload = {
        "courses": [
            {"course_id": course_a, "deadline": (today + timedelta(days=7)).isoformat()},
            {"course_id": course_b, "deadline": (today + timedelta(days=7)).isoformat()},
        ],
        "daily_minutes": 30,
    }
    resp = client.post("/api/v1/plans/multi", json=plan_payload, headers=headers)
    assert resp.status_code in (200, 201), resp.text
    plan_id = resp.json().get("multi_plan_id") or resp.json().get("id")
    assert plan_id is not None, resp.text

    # Directly create StudyGoal + StudyTask + MultiCoursePlanTask rows
    # so we have deterministic tasks regardless of LLM availability.
    db = db_module.SessionLocal()
    try:
        # Check if tasks already exist from the API call
        existing_tasks = (
            db.query(StudyTask)
            .join(MultiCoursePlanTask, MultiCoursePlanTask.task_id == StudyTask.id)
            .filter(MultiCoursePlanTask.multi_plan_id == plan_id)
            .all()
        )
        if not existing_tasks:
            from app.models.plan import StudyGoal
            for cid, cname in [(course_a, "Course-A"), (course_b, "Course-B")]:
                goal = StudyGoal(
                    user_id=user_id,
                    title=f"V742 Plan - {cname}",
                    deadline=today + timedelta(days=7),
                    daily_minutes=30,
                    status="active",
                )
                db.add(goal)
                db.flush()
                task = StudyTask(
                    goal_id=goal.id,
                    course_id=cid,
                    title=f"Study {cname} chapter 1",
                    task_type="learn",
                    estimate_minutes=30,
                    priority=3,
                    acceptance="complete reading",
                    execution_status=task_status,
                )
                db.add(task)
                db.flush()
                mpt = MultiCoursePlanTask(
                    multi_plan_id=plan_id,
                    task_id=task.id,
                    course_id=cid,
                    scheduled_date=today,
                    estimate_minutes=30,
                )
                db.add(mpt)
            db.commit()
        else:
            # Tasks were created by the API — update their status
            for t in existing_tasks:
                t.execution_status = task_status
            db.commit()
    finally:
        db.close()

    return plan_id, headers, user_id


class TestForceRemoved:
    """V7.4.2-05: force=true must be removed or rejected."""

    def test_force_parameter_rejected(self, client: TestClient):
        """DELETE with force=true on a plan with execution history must still return 409."""
        plan_id, headers, _ = _make_plan_with_tasks(client, "v742_force1", task_status="in_progress")
        resp = client.delete(
            f"/api/v1/plans/multi/{plan_id}?force=true",
            headers=headers,
        )
        # Must NOT be 204 — force should not bypass the safety check
        assert resp.status_code == 409, (
            f"force=true must not bypass safety check. Got status {resp.status_code}: {resp.text}"
        )

    def test_force_parameter_default_false_still_works_for_pristine(self, client: TestClient):
        """DELETE without force on a pristine plan should work."""
        plan_id, headers, _ = _make_plan_with_tasks(client, "v742_force2", task_status="pending")
        resp = client.delete(
            f"/api/v1/plans/multi/{plan_id}",
            headers=headers,
        )
        assert resp.status_code == 204


class TestArchiveEndpoint:
    """V7.4.2-05: POST /plans/multi/{id}/archive must exist and work."""

    def test_archive_endpoint_exists(self, client: TestClient):
        """POST /plans/multi/{id}/archive should return 200."""
        plan_id, headers, _ = _make_plan_with_tasks(client, "v742_archive1", task_status="in_progress")
        resp = client.post(
            f"/api/v1/plans/multi/{plan_id}/archive",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    def test_archive_sets_status_to_archived(self, client: TestClient):
        """After archiving, the plan status should be 'archived'."""
        plan_id, headers, _ = _make_plan_with_tasks(client, "v742_archive2", task_status="completed")
        resp = client.post(
            f"/api/v1/plans/multi/{plan_id}/archive",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "archived"

    def test_archived_plan_still_in_history(self, client: TestClient):
        """Archived plans should appear in the list with status filter."""
        plan_id, headers, _ = _make_plan_with_tasks(client, "v742_archive3", task_status="completed")
        client.post(f"/api/v1/plans/multi/{plan_id}/archive", headers=headers)

        # List archived plans
        resp = client.get("/api/v1/plans/multi?status=archived", headers=headers)
        assert resp.status_code == 200
        plans = resp.json()
        # Should find our archived plan
        found = any(p["id"] == plan_id for p in plans)
        assert found, f"Archived plan {plan_id} not found in archived plans list"


class TestSafeDelete:
    """V7.4.2-05: DELETE only works for pristine plans."""

    def test_delete_rejected_with_execution_history(self, client: TestClient):
        """Plans with execution history cannot be deleted."""
        plan_id, headers, _ = _make_plan_with_tasks(client, "v742_safe1", task_status="in_progress")
        resp = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        assert resp.status_code == 409
        # Plan should still exist
        get_resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        assert get_resp.status_code == 200

    def test_delete_succeeds_for_pristine_plan(self, client: TestClient):
        """Plans with only pending tasks can be deleted."""
        plan_id, headers, _ = _make_plan_with_tasks(client, "v742_safe2", task_status="pending")
        resp = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        assert resp.status_code == 204
        # Plan should be gone
        get_resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        assert get_resp.status_code == 404

    def test_delete_after_archive_still_rejected_if_has_history(self, client: TestClient):
        """Archiving a plan doesn't make it deletable if it has execution history."""
        plan_id, headers, _ = _make_plan_with_tasks(client, "v742_safe3", task_status="completed")
        # Archive first
        client.post(f"/api/v1/plans/multi/{plan_id}/archive", headers=headers)
        # Try to delete — should still fail
        resp = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        assert resp.status_code == 409
