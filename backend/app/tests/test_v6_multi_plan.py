"""V6-40: Multi-Course Plan API — GET / PATCH / DELETE / reschedule.

Strict TDD: these tests are written first and fail until the
GET/PATCH/DELETE/reschedule endpoints for multi-course plans are
implemented in ``app/api/v1/endpoints/plans.py``.

The POST /plans/multi endpoint already exists and returns a
``MultiPlanResponse``.  These tests exercise the new lifecycle endpoints
that operate on an already-created multi-plan.

Fixtures: ``client`` + ``auth_headers()`` + ``create_course`` from
conftest.py (HTTP-level tests).
"""
from app.tests.conftest import auth_headers, create_course
from app.api.deps import get_db
from app.main import app
from app.models.plan import StudyTask


def _create_multi_plan(client, headers, daily_minutes=120):
    """Create a multi-plan with two courses.

    Returns ``(response_body, plan_id, course_a_id, course_b_id)``.
    """
    course_a = create_course(client, headers, name="机器学习")
    course_b = create_course(client, headers, name="数据结构")
    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [
                {"course_id": course_a, "deadline": "2026-12-31"},
                {"course_id": course_b, "deadline": "2026-12-31"},
            ],
            "daily_minutes": daily_minutes,
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    plan_id = body.get("multi_plan_id")
    assert plan_id is not None, "POST /plans/multi must return multi_plan_id"
    return body, plan_id, course_a, course_b


# ---------------------------------------------------------------------------
# GET /plans/multi/{multi_plan_id}
# ---------------------------------------------------------------------------


def test_get_multi_plan(client) -> None:
    """Create a multi-plan, GET it, verify all fields."""
    headers = auth_headers(client, username="alice")
    _, plan_id, _, _ = _create_multi_plan(client, headers)

    resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == plan_id
    assert body["status"] == "active"
    assert "title" in body
    assert "deadline" in body
    assert "daily_minutes" in body
    assert body["daily_minutes"] == 120
    assert "tasks" in body
    assert isinstance(body["tasks"], list)
    assert len(body["tasks"]) >= 1
    # Each task should have the expected fields
    for task in body["tasks"]:
        assert "course_id" in task
        assert "course_name" in task
        assert "scheduled_date" in task
        assert "estimate_minutes" in task


def test_get_multi_plan_not_found(client) -> None:
    """GET non-existent plan -> 404."""
    headers = auth_headers(client, username="alice")
    resp = client.get("/api/v1/plans/multi/99999", headers=headers)
    assert resp.status_code == 404


def test_get_multi_plan_cross_user(client) -> None:
    """User A creates, User B GETs -> 404."""
    headers_a = auth_headers(client, username="alice")
    _, plan_id, _, _ = _create_multi_plan(client, headers_a)

    headers_b = auth_headers(client, username="bob")
    resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers_b)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /plans/multi/{multi_plan_id}
# ---------------------------------------------------------------------------


def test_patch_multi_plan_status(client) -> None:
    """PATCH status to 'archived'."""
    headers = auth_headers(client, username="alice")
    _, plan_id, _, _ = _create_multi_plan(client, headers)

    resp = client.patch(
        f"/api/v1/plans/multi/{plan_id}",
        json={"status": "archived"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == plan_id
    assert body["status"] == "archived"

    # Verify persistence: GET should also show archived
    resp2 = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "archived"


# ---------------------------------------------------------------------------
# DELETE /plans/multi/{multi_plan_id}
# ---------------------------------------------------------------------------


def test_delete_multi_plan(client) -> None:
    """DELETE removes the plan and associated tasks."""
    headers = auth_headers(client, username="alice")
    _, plan_id, _, _ = _create_multi_plan(client, headers)

    resp = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp.status_code == 204

    # GET should now 404
    resp2 = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp2.status_code == 404


def test_delete_multi_plan_not_found(client) -> None:
    """DELETE non-existent -> 404."""
    headers = auth_headers(client, username="alice")
    resp = client.delete("/api/v1/plans/multi/99999", headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /plans/multi/{multi_plan_id}/reschedule
# ---------------------------------------------------------------------------


def test_multi_plan_reschedule(client) -> None:
    """Create plan, reschedule with different daily_minutes."""
    headers = auth_headers(client, username="alice")
    _, plan_id, _, _ = _create_multi_plan(client, headers, daily_minutes=60)

    resp = client.post(
        f"/api/v1/plans/multi/{plan_id}/reschedule",
        json={"daily_minutes": 240},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "schedule" in body
    assert isinstance(body["schedule"], list)
    assert len(body["schedule"]) >= 1

    # The plan's daily_minutes should be updated
    resp2 = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["daily_minutes"] == 240


# ---------------------------------------------------------------------------
# Lifecycle: Create -> Get -> Patch -> Delete
# ---------------------------------------------------------------------------


def test_multi_plan_lifecycle(client) -> None:
    """Create -> Get -> Patch -> Delete lifecycle."""
    headers = auth_headers(client, username="alice")
    _, plan_id, _, _ = _create_multi_plan(client, headers)

    # GET — should be active
    resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

    # PATCH — mark done
    resp = client.patch(
        f"/api/v1/plans/multi/{plan_id}",
        json={"status": "done"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"

    # DELETE
    resp = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp.status_code == 204

    # GET after delete -> 404
    resp = client.get(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert resp.status_code == 404


def test_reschedule_keeps_completed_and_in_progress_task_history(client) -> None:
    headers = auth_headers(client, username="history")
    _, plan_id, _, _ = _create_multi_plan(client, headers)
    db = next(app.dependency_overrides[get_db]())
    try:
        tasks = db.query(StudyTask).order_by(StudyTask.id).all()
        assert tasks
        completed, in_progress = tasks[0], tasks[-1]
        completed.status = "done"
        completed.execution_status = "completed"
        in_progress.execution_status = "in_progress"
        db.commit()
        frozen_ids = {completed.id, in_progress.id}
    finally:
        db.close()

    response = client.post(
        f"/api/v1/plans/multi/{plan_id}/reschedule",
        json={"daily_minutes": 90}, headers=headers,
    )
    assert response.status_code == 200, response.text

    db = next(app.dependency_overrides[get_db]())
    try:
        frozen = db.query(StudyTask).filter(StudyTask.id.in_(frozen_ids)).all()
        assert {task.id for task in frozen} == frozen_ids
        assert {task.execution_status for task in frozen} == {"completed", "in_progress"}
        assert any(task.generation >= 2 for task in db.query(StudyTask).all())
    finally:
        db.close()
