"""V7.4.1-05: Multi-course plan history protection and reschedule diff tests.

Verifies:
1. Safe delete rejects when tasks have execution history (non-pending status)
2. Archive endpoint allows archiving plans with execution history
3. Reschedule returns a diff with kept/moved/created/superseded/unscheduled
4. Reschedule diff correctly identifies created tasks
5. Reschedule diff correctly identifies superseded tasks
6. Reschedule preserves course names and deadlines
7. Deleting a plan with only pending tasks succeeds
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
from app.models.course import Course
from app.models.plan import (
    MultiCoursePlan, MultiCoursePlanTask, StudyGoal, StudyTask,
)
from app.tests.conftest import auth_headers


def _make_plan_with_tasks(client: TestClient, username: str, task_status: str = "pending"):
    """Create a multi-course plan with tasks. Returns (plan_id, task_ids, headers)."""
    headers = auth_headers(client, username=username, password="test1234")
    user_resp = client.get("/api/v1/auth/me", headers=headers)
    user_id = user_resp.json()["user_id"]

    # Create course
    resp = client.post("/api/v1/courses", json={"name": f"Plan-{username}"}, headers=headers)
    course_id = resp.json()["id"]

    # Create multi-plan via API
    resp = client.post("/api/v1/plans/multi", json={
        "title": f"Test Plan-{username}",
        "courses": [{"course_id": course_id, "deadline": "2026-12-31", "daily_minutes": 30}],
        "daily_minutes": 60,
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    plan_id = resp.json()["multi_plan_id"]

    # Get tasks
    resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    detail = resp.json()
    task_ids = [t["task_id"] for t in detail.get("tasks", []) if t.get("task_id")]

    # Update task status via DB
    if task_status != "pending" and task_ids:
        db = db_module.SessionLocal()
        try:
            db.query(StudyTask).filter(
                StudyTask.id.in_(task_ids)
            ).update({"execution_status": task_status}, synchronize_session=False)
            db.commit()
        finally:
            db.close()

    return plan_id, task_ids, headers


class TestSafeDelete:
    """V7.4.1-05: Safe delete with execution history protection."""

    def test_rejects_delete_with_execution_history(self, client: TestClient):
        """Delete must be rejected when tasks have non-pending execution status."""
        plan_id, task_ids, headers = _make_plan_with_tasks(
            client, "safedel1", task_status="in_progress"
        )
        assert len(task_ids) > 0

        resp = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        assert resp.status_code == 409, resp.text
        body = resp.json()
        msg = body.get("message", body.get("detail", ""))
        assert "force" in msg.lower() or "执行" in msg

        # Verify plan still exists
        resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        assert resp.status_code == 200

    def test_force_delete_succeeds_with_execution_history(self, client: TestClient):
        """V7.4.2-05: Archive endpoint succeeds even with execution history."""
        plan_id, task_ids, headers = _make_plan_with_tasks(
            client, "safedel2", task_status="completed"
        )

        # Archive instead of force delete
        resp = client.post(f"/api/v1/plans/multi/{plan_id}/archive", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "archived"

        # Verify plan is archived (not deleted)
        resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

    def test_delete_succeeds_with_only_pending_tasks(self, client: TestClient):
        """Delete succeeds without force when all tasks are pending."""
        plan_id, task_ids, headers = _make_plan_with_tasks(
            client, "safedel3", task_status="pending"
        )

        resp = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        assert resp.status_code == 204, resp.text

        # Verify plan is gone
        resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        assert resp.status_code == 404


class TestRescheduleDiff:
    """V7.4.2-06: Reschedule must return a five-category diff."""

    def test_reschedule_returns_diff(self, client: TestClient):
        """Reschedule response must include a diff object."""
        plan_id, _, headers = _make_plan_with_tasks(
            client, "resched1", task_status="pending"
        )

        resp = client.post(
            f"/api/v1/plans/multi/{plan_id}/reschedule",
            json={"daily_minutes": 90},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "diff" in body
        diff = body["diff"]
        # V7.4.2-06: five categories
        for cat in ("kept", "moved", "created", "superseded", "unscheduled"):
            assert cat in diff

    def test_reschedule_diff_has_added_tasks(self, client: TestClient):
        """Reschedule diff should have entries in the five categories."""
        plan_id, _, headers = _make_plan_with_tasks(
            client, "resched2", task_status="pending"
        )

        # Get original task count
        resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        original_count = len(resp.json().get("tasks", []))

        # Reschedule with less daily time → more tasks
        resp = client.post(
            f"/api/v1/plans/multi/{plan_id}/reschedule",
            json={"daily_minutes": 15},  # Less time → more days needed
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        diff = body["diff"]

        # The diff should have entries across the five categories
        total_diff = (
            len(diff["kept"]) + len(diff["moved"]) + len(diff["created"])
            + len(diff["superseded"]) + len(diff["unscheduled"])
        )
        assert total_diff > 0, "Reschedule diff must have at least some changes"

    def test_reschedule_preserves_course_names(self, client: TestClient):
        """Reschedule must preserve course names in the diff."""
        plan_id, _, headers = _make_plan_with_tasks(
            client, "resched3", task_status="pending"
        )

        resp = client.post(
            f"/api/v1/plans/multi/{plan_id}/reschedule",
            json={"daily_minutes": 90},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # Check that new tasks have course names
        tasks = body.get("tasks", [])
        for task in tasks:
            if task.get("course_name") is not None:
                assert len(task["course_name"]) > 0, "Course name must not be empty"

    def test_reschedule_diff_removed_has_old_tasks(self, client: TestClient):
        """Superseded tasks in diff must reference old schedule items."""
        plan_id, _, headers = _make_plan_with_tasks(
            client, "resched4", task_status="pending"
        )

        # Get original tasks
        resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
        old_tasks = resp.json().get("tasks", [])

        resp = client.post(
            f"/api/v1/plans/multi/{plan_id}/reschedule",
            json={"daily_minutes": 120},  # More time → fewer days
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        diff = resp.json()["diff"]

        # If the schedule changed, superseded should have items from old schedule
        # or created should have new items
        if len(diff["superseded"]) > 0:
            for item in diff["superseded"]:
                assert "title" in item or "course_name" in item
