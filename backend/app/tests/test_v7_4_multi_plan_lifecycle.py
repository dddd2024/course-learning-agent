"""V7.4-04: Multi-course frontend-backend lifecycle tests.

Tests cover:
1. GET /plans/multi returns persisted plans from DB (not sessionStorage)
2. Unscheduled tasks carry title_snapshot and generation
3. Detail response filters by generation (unscheduled too)
4. History endpoint returns all generations
5. Reschedule returns a diff (added/removed/changed)
6. Safe delete: rejects when tasks have execution history
"""
from __future__ import annotations

import time
from datetime import date, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core import database as db_module
from app.core.security import hash_password
from app.models.course import Course
from app.models.plan import (
    MultiCoursePlan,
    MultiCoursePlanTask,
    StudyGoal,
    StudyTask,
    Todo,
)
from app.models.user import User


def _get_session():
    """Return a session from the (possibly patched) SessionLocal."""
    return db_module.SessionLocal()


def _auth_client(client: TestClient) -> tuple[int, dict]:
    """Register a user via API and get auth headers."""
    username = f"testuser_v74_{int(time.time() * 1000) % 100000}"
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


def _make_course(user_id: int, name="测试课程") -> Course:
    db = _get_session()
    try:
        course = Course(user_id=user_id, name=name, color="#409eff")
        db.add(course)
        db.commit()
        db.refresh(course)
        return course
    finally:
        db.close()


def _seed_multi_plan(
    user_id: int,
    course_id: int,
    *,
    generation_version: int = 1,
    with_execution: bool = False,
) -> MultiCoursePlan:
    """Create a multi-plan with one scheduled task and one unscheduled task."""
    db = _get_session()
    try:
        plan = MultiCoursePlan(
            user_id=user_id,
            title="多课程学习计划",
            deadline=date(2026, 12, 31),
            daily_minutes=120,
            status="active",
            generation_version=generation_version,
            constraints_json="{}",
        )
        db.add(plan)
        db.flush()

        goal = StudyGoal(
            user_id=user_id,
            title=f"多课程学习计划 - 测试课程",
            deadline=date(2026, 12, 31),
            daily_minutes=120,
            status="active",
        )
        db.add(goal)
        db.flush()

        task = StudyTask(
            goal_id=goal.id,
            course_id=course_id,
            title="学习第一章",
            task_type="learn",
            estimate_minutes=60,
            priority=3,
            acceptance="完成第一章",
            status="pending",
            execution_status="in_progress" if with_execution else "pending",
            generation=generation_version,
            schedule_status="active",
            started_at=datetime.now() if with_execution else None,
        )
        db.add(task)
        db.flush()

        db.add(MultiCoursePlanTask(
            multi_plan_id=plan.id,
            task_id=task.id,
            course_id=course_id,
            depends_on_json="[]",
            scheduled_date=date(2026, 7, 15),
            estimate_minutes=60,
        ))

        # Unscheduled task — V7.4-04: must carry title_snapshot and generation
        db.add(MultiCoursePlanTask(
            multi_plan_id=plan.id,
            task_id=None,
            course_id=course_id,
            depends_on_json="[]",
            scheduled_date=None,
            estimate_minutes=30,
            unscheduled_reason="超出截止日期",
            title_snapshot="未排期的任务标题",
            generation=generation_version,
        ))
        db.commit()
        db.refresh(plan)
        return plan
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. GET /plans/multi returns persisted plans from DB
# ---------------------------------------------------------------------------

class TestListMultiPlans:
    """V7.4-04: MultiPlanView should use GET /plans/multi, not sessionStorage."""

    def test_list_returns_plans_from_db(self, client: TestClient):
        """GET /plans/multi returns plans persisted in DB, not sessionStorage."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)
        plan = _seed_multi_plan(user_id, course.id)

        resp = client.get("/api/v1/plans/multi", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        found = [p for p in data if p["id"] == plan.id]
        assert len(found) == 1
        assert found[0]["title"] == plan.title
        assert found[0]["task_count"] >= 1

    def test_list_filters_by_status(self, client: TestClient):
        """GET /plans/multi?status=active filters correctly."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)
        plan = _seed_multi_plan(user_id, course.id)

        resp = client.get("/api/v1/plans/multi?status=active", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert all(p["status"] == "active" for p in data)

        resp2 = client.get("/api/v1/plans/multi?status=archived", headers=headers)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert all(p["status"] == "archived" for p in data2)


# ---------------------------------------------------------------------------
# 2. Unscheduled task carries title_snapshot and generation
# ---------------------------------------------------------------------------

class TestUnscheduledTaskSnapshot:
    """V7.4-04: Unscheduled tasks must preserve title_snapshot and generation."""

    def test_model_has_title_snapshot_column(self):
        """MultiCoursePlanTask model has title_snapshot column."""
        from app.models.plan import MultiCoursePlanTask as MCPT
        assert hasattr(MCPT, "title_snapshot"), (
            "MultiCoursePlanTask must have a title_snapshot column for unscheduled tasks"
        )

    def test_model_has_generation_column(self):
        """MultiCoursePlanTask model has generation column."""
        from app.models.plan import MultiCoursePlanTask as MCPT
        assert hasattr(MCPT, "generation"), (
            "MultiCoursePlanTask must have a generation column"
        )

    def test_detail_returns_title_snapshot_for_unscheduled(self, client: TestClient):
        """GET /plans/multi/{id} returns title_snapshot for unscheduled tasks."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)
        plan = _seed_multi_plan(user_id, course.id)

        resp = client.get(f"/api/v1/plans/multi/{plan.id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        unscheduled = [t for t in data["tasks"] if t["unscheduled_reason"]]
        assert len(unscheduled) >= 1
        # Must use title_snapshot, not the placeholder "（未排程任务）"
        assert unscheduled[0]["title"] == "未排期的任务标题"


# ---------------------------------------------------------------------------
# 3. Generation filter in detail response
# ---------------------------------------------------------------------------

class TestGenerationFilter:
    """V7.4-04: Detail response filters unscheduled tasks by generation too."""

    def test_detail_excludes_old_generation_unscheduled(self, client: TestClient):
        """Unscheduled tasks from old generation are excluded from detail."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)
        plan = _seed_multi_plan(user_id, course.id, generation_version=2)

        # Add an unscheduled task from generation 1 (old)
        db = _get_session()
        try:
            db.add(MultiCoursePlanTask(
                multi_plan_id=plan.id,
                task_id=None,
                course_id=course.id,
                depends_on_json="[]",
                scheduled_date=None,
                estimate_minutes=30,
                unscheduled_reason="旧版本任务",
                title_snapshot="旧任务",
                generation=1,
            ))
            db.commit()
        finally:
            db.close()

        resp = client.get(f"/api/v1/plans/multi/{plan.id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        titles = [t["title"] for t in data["tasks"]]
        assert "旧任务" not in titles


# ---------------------------------------------------------------------------
# 4. History endpoint returns all generations
# ---------------------------------------------------------------------------

class TestHistoryEndpoint:
    """V7.4-04: History endpoint returns tasks from all generations."""

    def test_history_returns_all_generations(self, client: TestClient):
        """GET /plans/multi/{id}/history returns tasks from every generation."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)
        plan = _seed_multi_plan(user_id, course.id, generation_version=2)

        # Add an old-gen unscheduled task
        db = _get_session()
        try:
            db.add(MultiCoursePlanTask(
                multi_plan_id=plan.id,
                task_id=None,
                course_id=course.id,
                depends_on_json="[]",
                scheduled_date=None,
                estimate_minutes=30,
                unscheduled_reason="旧版本任务",
                title_snapshot="旧任务",
                generation=1,
            ))
            db.commit()
        finally:
            db.close()

        resp = client.get(f"/api/v1/plans/multi/{plan.id}/history", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        titles = [t["title"] for t in data]
        assert "旧任务" in titles
        assert "未排期的任务标题" in titles


# ---------------------------------------------------------------------------
# 5. Reschedule returns diff
# ---------------------------------------------------------------------------

class TestRescheduleDiff:
    """V7.4-04: Reschedule response includes a diff of added/removed/changed tasks."""

    def test_reschedule_response_has_diff_field(self, client: TestClient):
        """POST /plans/multi/{id}/reschedule returns a diff field."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)
        plan = _seed_multi_plan(user_id, course.id)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = {
                "schedule": [
                    {
                        "course_id": course.id,
                        "course_name": course.name,
                        "title": "新任务",
                        "task_type": "learn",
                        "estimate_minutes": 60,
                        "priority": 3,
                        "scheduled_date": date(2026, 7, 20),
                        "acceptance": "完成",
                    }
                ],
                "overflow_warnings": [],
                "unscheduled_tasks": [],
            }
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "diff" in data, "Reschedule response must include a 'diff' field"
        diff = data["diff"]
        # V7.4.2-06: diff now uses five categories instead of added/removed/changed
        assert "kept" in diff
        assert "moved" in diff
        assert "created" in diff
        assert "superseded" in diff
        assert "unscheduled" in diff


# ---------------------------------------------------------------------------
# 6. Safe delete with execution history check
# ---------------------------------------------------------------------------

class TestSafeDelete:
    """V7.4-04: Delete rejects when tasks have execution history."""

    def test_delete_rejects_when_task_has_execution(self, client: TestClient):
        """DELETE /plans/multi/{id} returns 409 when tasks have execution history."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)
        plan = _seed_multi_plan(user_id, course.id, with_execution=True)

        resp = client.delete(f"/api/v1/plans/multi/{plan.id}", headers=headers)
        assert resp.status_code == 409, (
            f"Delete should be rejected (409) when tasks have execution history, "
            f"got {resp.status_code}: {resp.text}"
        )
        # Plan must still exist
        db = _get_session()
        try:
            assert db.query(MultiCoursePlan).filter_by(id=plan.id).first() is not None
        finally:
            db.close()

    def test_delete_succeeds_when_no_execution(self, client: TestClient):
        """DELETE /plans/multi/{id} succeeds when tasks have no execution history."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)
        plan = _seed_multi_plan(user_id, course.id)

        resp = client.delete(f"/api/v1/plans/multi/{plan.id}", headers=headers)
        assert resp.status_code == 204
        db = _get_session()
        try:
            assert db.query(MultiCoursePlan).filter_by(id=plan.id).first() is None
        finally:
            db.close()

    def test_delete_with_force_flag_bypasses_check(self, client: TestClient):
        """V7.4.2-05: Force delete is removed; archive is used instead."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)
        plan = _seed_multi_plan(user_id, course.id, with_execution=True)

        # Force delete is no longer supported; should return 409
        resp = client.delete(f"/api/v1/plans/multi/{plan.id}?force=true", headers=headers)
        assert resp.status_code == 409

        # Archive should succeed
        resp = client.post(f"/api/v1/plans/multi/{plan.id}/archive", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"


# ---------------------------------------------------------------------------
# 7. Frontend API: listMultiPlans function exists
# ---------------------------------------------------------------------------

class TestFrontendApiHasListMultiPlans:
    """V7.4-04: Frontend API must have a listMultiPlans function."""

    def test_plan_ts_exports_list_multi_plans(self):
        """plan.ts must export a listMultiPlans function."""
        import os
        plan_ts_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "frontend", "src", "api", "plan.ts",
        )
        if not os.path.exists(plan_ts_path):
            pytest.skip("Frontend source not found")
        with open(plan_ts_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "listMultiPlans" in content, (
            "plan.ts must export a listMultiPlans function to replace sessionStorage"
        )
