"""Tests for the dashboard summary endpoint (Task B).

Strict TDD: these tests are written first and fail until the
``GET /api/v1/dashboard/summary`` endpoint is implemented.

Covers:
- Unauthorized request returns 401.
- Empty account returns all-zero counts.
- Counts reflect the user's courses / materials / knowledge points /
  todos (today + completed) / agent runs.
- Cross-user isolation: user B's summary does not include user A's data.
"""
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.main import app
from app.models.audit import AgentRun
from app.models.knowledge_point import KnowledgePoint
from app.models.plan import StudyGoal, StudyTask, Todo
from app.models.user import User
from app.tests.conftest import (
    auth_headers,
    create_course,
    setup_course_with_material,
)


def _get_db_session() -> Session:
    """Return the test DB session used by the overridden get_db."""
    return next(app.dependency_overrides[get_db]())


def test_dashboard_unauthorized(client) -> None:
    """GET /dashboard/summary without a token returns 401."""
    resp = client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 401


def test_dashboard_empty(client) -> None:
    """A fresh account sees all-zero counts."""
    headers = auth_headers(client, username="alice")
    resp = client.get("/api/v1/dashboard/summary", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["course_count"] == 0
    assert body["material_count"] == 0
    assert body["knowledge_point_count"] == 0
    assert body["todo_today_count"] == 0
    assert body["todo_completed_count"] == 0
    assert body["agent_run_count"] == 0


def test_dashboard_counts(client, tmp_path, monkeypatch) -> None:
    """Counts match the user's data across all six dimensions."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    # 1 course + 1 ready material (with chunks).
    course_id, _ = setup_course_with_material(client, headers)

    db = _get_db_session()
    try:
        user = db.query(User).filter(User.username == "alice").first()
        assert user is not None

        # 1 knowledge point.
        db.add(
            KnowledgePoint(
                course_id=course_id,
                user_id=user.id,
                title="测试知识点",
                importance=3,
            )
        )

        # 1 goal + 1 task -> 2 todos (1 pending today, 1 completed today).
        goal = StudyGoal(
            user_id=user.id,
            title="复习计划",
            deadline=date.today(),
            daily_minutes=120,
        )
        db.add(goal)
        db.flush()
        task = StudyTask(
            goal_id=goal.id,
            course_id=course_id,
            title="任务1",
            task_type="review",
        )
        db.add(task)
        db.flush()
        db.add(
            Todo(
                user_id=user.id,
                task_id=task.id,
                course_id=course_id,
                title="今日待办",
                scheduled_date=date.today(),
                status="pending",
            )
        )
        db.add(
            Todo(
                user_id=user.id,
                task_id=task.id,
                course_id=course_id,
                title="已完成待办",
                scheduled_date=date.today(),
                status="completed",
                completed_at=datetime(2026, 7, 6, 12, 0, 0),
            )
        )

        # 1 agent run.
        db.add(
            AgentRun(
                user_id=user.id,
                run_type="course_qa",
                status="success",
                started_at=datetime(2026, 7, 6, 12, 0, 0),
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/v1/dashboard/summary", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["course_count"] == 1
    assert body["material_count"] == 1
    assert body["knowledge_point_count"] == 1
    # Dashboard label says "今日待办"; completed items are reported by the
    # separate completed counter and must not inflate actionable work.
    assert body["todo_today_count"] == 1
    assert body["todo_completed_count"] == 1
    assert body["agent_run_count"] == 1


def test_dashboard_isolation(client) -> None:
    """User B's summary does not leak user A's course."""
    headers_a = auth_headers(client, username="alice")
    create_course(client, headers_a, "操作系统")

    headers_b = auth_headers(client, username="bob")
    resp = client.get("/api/v1/dashboard/summary", headers=headers_b)
    assert resp.status_code == 200
    assert resp.json()["course_count"] == 0
