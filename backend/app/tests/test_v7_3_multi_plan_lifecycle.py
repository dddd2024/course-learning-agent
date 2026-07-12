"""V7.3-03 P1-01/02/03: Multi-course plan persistence lifecycle.

Tests that:
- Unscheduled tasks (task_id=None) are preserved in the detail response
- GET /plans/multi returns a list of all multi-plans for the user
- GET /plans/multi/{id}/history returns tasks from all generations
- MultiPlanTaskItem includes task_status and generation
- DELETE /plans/multi/{id} removes the plan
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core import database as db_module
from app.models.plan import MultiCoursePlan, MultiCoursePlanTask, StudyGoal, StudyTask
from app.models.course import Course
from app.models.user import User


def _get_session():
    """Return a session from the (possibly patched) SessionLocal.

    The ``client`` fixture monkeypatches ``app.core.database.SessionLocal``
    at the module level.  By accessing it via the module attribute (rather
    than a top-level ``from … import SessionLocal``) we always get the
    patched version when the ``client`` fixture is active.
    """
    return db_module.SessionLocal()


def _auth_client(client: TestClient) -> tuple[int, dict]:
    """Register a user via API and get auth headers."""
    username = f"testuser_pl_{int(time.time() * 1000) % 100000}"
    resp = client.post("/api/v1/auth/register", json={
        "username": username,
        "password": "secret123",
        "email": f"{username}@test.com",
    })
    assert resp.status_code in (200, 201), resp.text
    resp = client.post("/api/v1/auth/login", json={
        "username": username,
        "password": "secret123",
    })
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    db = _get_session()
    try:
        user = db.query(User).filter(User.username == username).first()
        assert user is not None, f"User {username} not found after registration"
        return user.id, {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _make_course(user_id: int, name="Test Course") -> Course:
    """Create a course via DB (same session as client)."""
    db = _get_session()
    try:
        course = Course(user_id=user_id, name=name)
        db.add(course)
        db.commit()
        db.refresh(course)
        return course
    finally:
        db.close()


def test_unscheduled_tasks_preserved_in_detail(client: TestClient):
    """Unscheduled tasks (task_id=None) must appear in GET /plans/multi/{id}."""
    user_id, headers = _auth_client(client)
    course = _make_course(user_id)

    db = _get_session()
    try:
        plan = MultiCoursePlan(
            user_id=user_id,
            title="Test Plan",
            status="active",
            deadline=date.today() + timedelta(days=7),
            daily_minutes=60,
            generation_version=1,
        )
        db.add(plan)
        db.flush()

        goal = StudyGoal(user_id=user_id, title="Goal 1", deadline=date.today() + timedelta(days=7))
        db.add(goal)
        db.flush()
        task = StudyTask(
            course_id=course.id,
            goal_id=goal.id,
            title="Scheduled Task",
            task_type="study",
            target_type="material",
            status="pending",
            generation=1,
        )
        db.add(task)
        db.flush()

        db.add(MultiCoursePlanTask(
            multi_plan_id=plan.id,
            task_id=task.id,
            course_id=course.id,
            scheduled_date=date.today(),
            estimate_minutes=30,
        ))
        db.add(MultiCoursePlanTask(
            multi_plan_id=plan.id,
            task_id=None,
            course_id=course.id,
            scheduled_date=None,
            estimate_minutes=45,
            unscheduled_reason="时间不足",
        ))
        db.commit()
        plan_id = plan.id
    finally:
        db.close()

    resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["tasks"]) >= 2
    unscheduled = [t for t in data["tasks"] if t["task_id"] is None]
    assert len(unscheduled) >= 1
    assert unscheduled[0]["unscheduled_reason"] == "时间不足"


def test_multi_plan_list_endpoint(client: TestClient):
    """GET /plans/multi must return all multi-plans for the user."""
    user_id, headers = _auth_client(client)

    db = _get_session()
    try:
        for i in range(3):
            db.add(MultiCoursePlan(
                user_id=user_id,
                title=f"Plan {i}",
                status="active" if i < 2 else "archived",
                deadline=date.today() + timedelta(days=7 + i),
                daily_minutes=60,
                generation_version=1,
            ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/v1/plans/multi", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 3
    for item in data:
        assert "id" in item
        assert "title" in item
        assert "status" in item
        assert "deadline" in item


def test_multi_plan_list_filter_active(client: TestClient):
    """GET /plans/multi?status=active must filter by status."""
    user_id, headers = _auth_client(client)

    db = _get_session()
    try:
        for i in range(3):
            db.add(MultiCoursePlan(
                user_id=user_id,
                title=f"Plan {i}",
                status="active" if i < 2 else "archived",
                deadline=date.today() + timedelta(days=7),
                daily_minutes=60,
                generation_version=1,
            ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/v1/plans/multi?status=active", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert all(item["status"] == "active" for item in data)


def test_multi_plan_history_endpoint(client: TestClient):
    """GET /plans/multi/{id}/history must return tasks from all generations."""
    user_id, headers = _auth_client(client)
    course = _make_course(user_id)

    db = _get_session()
    try:
        plan = MultiCoursePlan(
            user_id=user_id,
            title="Test Plan",
            status="active",
            deadline=date.today() + timedelta(days=7),
            daily_minutes=60,
            generation_version=2,
        )
        db.add(plan)
        db.flush()

        goal = StudyGoal(user_id=user_id, title="Goal 1", deadline=date.today() + timedelta(days=7))
        db.add(goal)
        db.flush()

        for gen in [1, 2]:
            task = StudyTask(
                course_id=course.id,
                goal_id=goal.id,
                title=f"Task Gen {gen}",
                task_type="study",
                target_type="material",
                status="completed" if gen == 1 else "pending",
                generation=gen,
            )
            db.add(task)
            db.flush()
            db.add(MultiCoursePlanTask(
                multi_plan_id=plan.id,
                task_id=task.id,
                course_id=course.id,
                scheduled_date=date.today(),
                estimate_minutes=30,
            ))
        db.commit()
        plan_id = plan.id
    finally:
        db.close()

    resp = client.get(f"/api/v1/plans/multi/{plan_id}/history", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 2
    generations = {t.get("generation") for t in data}
    assert 1 in generations
    assert 2 in generations


def test_multi_plan_detail_includes_task_status(client: TestClient):
    """MultiPlanTaskItem must include task status."""
    user_id, headers = _auth_client(client)
    course = _make_course(user_id)

    db = _get_session()
    try:
        plan = MultiCoursePlan(
            user_id=user_id,
            title="Test Plan",
            status="active",
            deadline=date.today() + timedelta(days=7),
            daily_minutes=60,
            generation_version=1,
        )
        db.add(plan)
        db.flush()

        goal = StudyGoal(user_id=user_id, title="Goal 1", deadline=date.today() + timedelta(days=7))
        db.add(goal)
        db.flush()
        task = StudyTask(
            course_id=course.id,
            goal_id=goal.id,
            title="Task",
            task_type="study",
            target_type="material",
            status="completed",
            generation=1,
        )
        db.add(task)
        db.flush()
        db.add(MultiCoursePlanTask(
            multi_plan_id=plan.id,
            task_id=task.id,
            course_id=course.id,
            scheduled_date=date.today(),
            estimate_minutes=30,
        ))
        db.commit()
        plan_id = plan.id
    finally:
        db.close()

    resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["tasks"]) >= 1
    assert data["tasks"][0]["task_status"] == "completed"


def test_multi_plan_delete(client: TestClient):
    """DELETE /plans/multi/{id} must remove the plan."""
    user_id, headers = _auth_client(client)

    db = _get_session()
    try:
        plan = MultiCoursePlan(
            user_id=user_id,
            title="Test Plan",
            status="active",
            deadline=date.today() + timedelta(days=7),
            daily_minutes=60,
            generation_version=1,
        )
        db.add(plan)
        db.commit()
        plan_id = plan.id
    finally:
        db.close()

    resp = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp.status_code == 204, resp.text
    # Subsequent GET should return 404
    resp2 = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp2.status_code == 404
