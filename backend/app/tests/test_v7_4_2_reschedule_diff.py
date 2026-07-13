"""V7.4.2-06: Five-category reschedule diff.

Tests that the reschedule response returns a diff with five categories:
  kept / moved / created / superseded / unscheduled

Each diff item must carry:
  stable_task_key, old_task_id, new_task_id,
  old_scheduled_date, new_scheduled_date,
  old_generation, new_generation, reason,
  title, course_name, estimate_minutes
"""
from __future__ import annotations

import re
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
    return db_module.SessionLocal()


def _auth_client(client: TestClient) -> tuple[int, dict]:
    username = f"v742diff_{int(time.time() * 1000) % 100000}"
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


def _make_course(user_id: int, name: str = "测试课程") -> Course:
    db = _get_session()
    try:
        course = Course(user_id=user_id, name=name, color="#409eff")
        db.add(course)
        db.commit()
        db.refresh(course)
        return course
    finally:
        db.close()


def _stable_key(course_id: int, task_type: str, title: str) -> str:
    return f"{course_id}:{task_type}:{re.sub(r'\\s+', '', title).lower()}"


def _seed_plan_with_tasks(
    user_id: int,
    course_id: int,
    tasks: list[dict],
) -> MultiCoursePlan:
    """Seed a multi-plan with explicit stable_task_key on each task.

    Each task dict: {title, task_type, scheduled_date, estimate_minutes, stable_key}
    """
    db = _get_session()
    try:
        plan = MultiCoursePlan(
            user_id=user_id,
            title="多课程学习计划",
            deadline=date(2026, 12, 31),
            daily_minutes=120,
            status="active",
            generation_version=1,
            constraints_json="{}",
        )
        db.add(plan)
        db.flush()

        goal = StudyGoal(
            user_id=user_id,
            title="多课程学习计划 - 测试课程",
            deadline=date(2026, 12, 31),
            daily_minutes=120,
            status="active",
        )
        db.add(goal)
        db.flush()

        for t in tasks:
            task = StudyTask(
                goal_id=goal.id,
                course_id=course_id,
                title=t["title"],
                task_type=t.get("task_type", "learn"),
                estimate_minutes=t.get("estimate_minutes", 60),
                priority=3,
                acceptance="done",
                status="pending",
                execution_status="pending",
                generation=1,
                schedule_status="active",
                stable_task_key=t["stable_key"],
            )
            db.add(task)
            db.flush()
            db.add(MultiCoursePlanTask(
                multi_plan_id=plan.id,
                task_id=task.id,
                course_id=course_id,
                depends_on_json="[]",
                scheduled_date=t["scheduled_date"],
                estimate_minutes=t.get("estimate_minutes", 60),
            ))
        db.commit()
        db.refresh(plan)
        return plan
    finally:
        db.close()


def _mock_schedule_return(course_id: int, course_name: str, items: list[dict]):
    """Build a fake schedule_multi_courses return value."""
    return {
        "schedule": [
            {
                "course_id": course_id,
                "course_name": course_name,
                "title": it["title"],
                "task_type": it.get("task_type", "learn"),
                "estimate_minutes": it.get("estimate_minutes", 60),
                "priority": 3,
                "scheduled_date": it["scheduled_date"],
                "acceptance": "done",
            }
            for it in items
        ],
        "overflow_warnings": [],
        "unscheduled_tasks": [
            {
                "course_id": course_id,
                "course_name": course_name,
                "title": it["title"],
                "estimate_minutes": it.get("estimate_minutes", 60),
                "deadline": date(2026, 12, 31),
                "reason": it.get("reason", "超出预算"),
                "suggestion": "增加每日学习时间",
            }
            for it in items if it.get("unscheduled")
        ],
    }


# ---------------------------------------------------------------------------
# 1. Five categories exist in diff
# ---------------------------------------------------------------------------

class TestFiveCategoryDiff:
    """V7.4.2-06: diff must have kept/moved/created/superseded/unscheduled."""

    def test_diff_has_five_categories(self, client: TestClient):
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        # Old tasks: A (will be kept), B (will be moved), C (will be superseded)
        old_tasks = [
            {"title": "Task-A", "stable_key": _stable_key(course.id, "learn", "Task-A"),
             "scheduled_date": date(2026, 7, 15)},
            {"title": "Task-B", "stable_key": _stable_key(course.id, "learn", "Task-B"),
             "scheduled_date": date(2026, 7, 16)},
            {"title": "Task-C", "stable_key": _stable_key(course.id, "learn", "Task-C"),
             "scheduled_date": date(2026, 7, 17)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        # New schedule: A (same date → kept), B (different date → moved), D (new → created)
        new_items = [
            {"title": "Task-A", "scheduled_date": date(2026, 7, 15)},
            {"title": "Task-B", "scheduled_date": date(2026, 7, 20)},
            {"title": "Task-D", "scheduled_date": date(2026, 7, 21)},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        assert resp.status_code == 200, resp.text
        diff = resp.json()["diff"]
        for cat in ("kept", "moved", "created", "superseded", "unscheduled"):
            assert cat in diff, f"diff must include '{cat}' category"

    def test_kept_items_have_matching_key_and_date(self, client: TestClient):
        """kept: same stable_task_key, same scheduled_date."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        old_tasks = [
            {"title": "Task-Keep", "stable_key": _stable_key(course.id, "learn", "Task-Keep"),
             "scheduled_date": date(2026, 7, 15)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        new_items = [
            {"title": "Task-Keep", "scheduled_date": date(2026, 7, 15)},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        diff = resp.json()["diff"]
        assert len(diff["kept"]) == 1
        item = diff["kept"][0]
        assert item["stable_task_key"] == _stable_key(course.id, "learn", "Task-Keep")
        assert item["reason"] == "kept"

    def test_moved_items_have_matching_key_different_date(self, client: TestClient):
        """moved: same stable_task_key, different scheduled_date."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        old_tasks = [
            {"title": "Task-Move", "stable_key": _stable_key(course.id, "learn", "Task-Move"),
             "scheduled_date": date(2026, 7, 15)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        new_items = [
            {"title": "Task-Move", "scheduled_date": date(2026, 7, 20)},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        diff = resp.json()["diff"]
        assert len(diff["moved"]) == 1
        item = diff["moved"][0]
        assert item["old_scheduled_date"] == "2026-07-15"
        assert item["new_scheduled_date"] == "2026-07-20"
        assert item["reason"] == "moved"

    def test_created_items_are_new(self, client: TestClient):
        """created: new stable_task_key not in old schedule."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        old_tasks = [
            {"title": "Task-Old", "stable_key": _stable_key(course.id, "learn", "Task-Old"),
             "scheduled_date": date(2026, 7, 15)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        new_items = [
            {"title": "Task-Old", "scheduled_date": date(2026, 7, 15)},
            {"title": "Task-New", "scheduled_date": date(2026, 7, 16)},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        diff = resp.json()["diff"]
        assert len(diff["created"]) == 1
        item = diff["created"][0]
        assert "task-new" in item["stable_task_key"].lower()
        assert item["reason"] == "created"

    def test_superseded_items_are_old_only(self, client: TestClient):
        """superseded: old stable_task_key not in new schedule."""
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        old_tasks = [
            {"title": "Task-Keep", "stable_key": _stable_key(course.id, "learn", "Task-Keep"),
             "scheduled_date": date(2026, 7, 15)},
            {"title": "Task-Gone", "stable_key": _stable_key(course.id, "learn", "Task-Gone"),
             "scheduled_date": date(2026, 7, 16)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        new_items = [
            {"title": "Task-Keep", "scheduled_date": date(2026, 7, 15)},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        diff = resp.json()["diff"]
        assert len(diff["superseded"]) == 1
        item = diff["superseded"][0]
        assert "task-gone" in item["stable_task_key"].lower()
        assert item["reason"] == "superseded"


# ---------------------------------------------------------------------------
# 2. Diff item fields
# ---------------------------------------------------------------------------

class TestDiffItemFields:
    """V7.4.2-06: Each diff item must carry all required fields."""

    def test_kept_item_has_all_fields(self, client: TestClient):
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        old_tasks = [
            {"title": "Task-A", "stable_key": _stable_key(course.id, "learn", "Task-A"),
             "scheduled_date": date(2026, 7, 15)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        new_items = [
            {"title": "Task-A", "scheduled_date": date(2026, 7, 15)},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        item = resp.json()["diff"]["kept"][0]
        required = {
            "stable_task_key", "old_task_id", "new_task_id",
            "old_scheduled_date", "new_scheduled_date",
            "old_generation", "new_generation", "reason",
            "title", "course_name", "estimate_minutes",
        }
        missing = required - set(item.keys())
        assert not missing, f"kept item missing fields: {missing}"

    def test_moved_item_has_old_and_new_ids(self, client: TestClient):
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        old_tasks = [
            {"title": "Task-M", "stable_key": _stable_key(course.id, "learn", "Task-M"),
             "scheduled_date": date(2026, 7, 15)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        new_items = [
            {"title": "Task-M", "scheduled_date": date(2026, 7, 20)},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        item = resp.json()["diff"]["moved"][0]
        assert item["old_task_id"] is not None
        assert item["new_task_id"] is not None
        assert item["old_task_id"] != item["new_task_id"]
        assert item["old_generation"] == 1
        assert item["new_generation"] == 2

    def test_created_item_has_new_id_only(self, client: TestClient):
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        old_tasks = [
            {"title": "Task-Old", "stable_key": _stable_key(course.id, "learn", "Task-Old"),
             "scheduled_date": date(2026, 7, 15)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        new_items = [
            {"title": "Task-Old", "scheduled_date": date(2026, 7, 15)},
            {"title": "Task-New", "scheduled_date": date(2026, 7, 16)},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        item = resp.json()["diff"]["created"][0]
        assert item["old_task_id"] is None
        assert item["new_task_id"] is not None
        assert item["old_generation"] is None
        assert item["new_generation"] == 2

    def test_superseded_item_has_old_id_only(self, client: TestClient):
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        old_tasks = [
            {"title": "Task-Keep", "stable_key": _stable_key(course.id, "learn", "Task-Keep"),
             "scheduled_date": date(2026, 7, 15)},
            {"title": "Task-Gone", "stable_key": _stable_key(course.id, "learn", "Task-Gone"),
             "scheduled_date": date(2026, 7, 16)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        new_items = [
            {"title": "Task-Keep", "scheduled_date": date(2026, 7, 15)},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        item = resp.json()["diff"]["superseded"][0]
        assert item["old_task_id"] is not None
        assert item["new_task_id"] is None
        assert item["old_generation"] == 1
        assert item["new_generation"] is None

    def test_unscheduled_item_has_reason(self, client: TestClient):
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        old_tasks = [
            {"title": "Task-A", "stable_key": _stable_key(course.id, "learn", "Task-A"),
             "scheduled_date": date(2026, 7, 15)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        new_items = [
            {"title": "Task-A", "scheduled_date": date(2026, 7, 15)},
            {"title": "Task-Unsched", "scheduled_date": date(2026, 7, 16),
             "unscheduled": True, "reason": "每日预算不足"},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        diff = resp.json()["diff"]
        assert len(diff["unscheduled"]) >= 1
        item = diff["unscheduled"][0]
        assert "reason" in item
        assert item["reason"]


# ---------------------------------------------------------------------------
# 3. Old generation preserved with schedule_status
# ---------------------------------------------------------------------------

class TestOldGenerationPreserved:
    """V7.4.2-06: Old tasks must have schedule_status='superseded' after reschedule."""

    def test_old_pending_tasks_marked_superseded(self, client: TestClient):
        user_id, headers = _auth_client(client)
        course = _make_course(user_id)

        old_tasks = [
            {"title": "Task-Gone", "stable_key": _stable_key(course.id, "learn", "Task-Gone"),
             "scheduled_date": date(2026, 7, 17)},
        ]
        plan = _seed_plan_with_tasks(user_id, course.id, old_tasks)

        new_items = [
            {"title": "Task-New", "scheduled_date": date(2026, 7, 15)},
        ]
        mock_return = _mock_schedule_return(course.id, course.name, new_items)

        with patch("app.api.v1.endpoints.plans.schedule_multi_courses") as mock_sched:
            mock_sched.return_value = mock_return
            resp = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 180},
                headers=headers,
            )

        assert resp.status_code == 200

        # Verify old task has schedule_status = "superseded"
        db = _get_session()
        try:
            old_task = (
                db.query(StudyTask)
                .filter(StudyTask.stable_task_key == _stable_key(course.id, "learn", "Task-Gone"))
                .first()
            )
            assert old_task is not None
            assert old_task.schedule_status == "superseded"
        finally:
            db.close()
