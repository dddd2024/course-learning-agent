"""Tests for the study-plan and todo module (BE-10, AG-06).

Strict TDD: these tests are written first and fail until the
``StudyGoal`` / ``StudyTask`` / ``Todo`` models, ``PlannerAgent``,
``scheduler`` service, plans router, and their schemas are implemented.

Covers:
- POST /api/v1/plans (create plan with goal + tasks + todos)
- GET  /api/v1/plans (persisted goal list with progress)
- GET  /api/v1/plans/{id} (restore tasks + todos after refresh)
- GET  /api/v1/todos (list by date / status / course_id, user-scoped)
- PATCH /api/v1/todos/{id} (complete / postpone, isolation)
- PlannerAgent.generate unit test (persistable task JSON)
- scheduler.schedule_tasks unit test (daily total <= daily_minutes)
"""
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from app.agents.planner import generate as planner_generate
from app.api.deps import get_db
from app.main import app
from app.services.scheduler import schedule_tasks
from app.tests.conftest import auth_headers, create_course


def _create_plan(
    client,
    headers: dict[str, str],
    goal: str = "7天复习完操作系统",
    courses: list[str] | None = None,
    deadline: str = "2026-07-30",
    daily_minutes: int = 120,
):
    """Helper: create a course + plan, return the plan response."""
    if courses is None:
        courses = ["操作系统"]
    for name in courses:
        create_course(client, headers, name)

    resp = client.post(
        "/api/v1/plans",
        json={
            "goal": goal,
            "courses": courses,
            "deadline": deadline,
            "daily_minutes": daily_minutes,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_plan(client) -> None:
    """POST /api/v1/plans returns 200 with goal, tasks, todos."""
    headers = auth_headers(client, username="alice")

    body = _create_plan(client, headers)

    # goal block
    assert "goal" in body
    goal = body["goal"]
    assert "id" in goal
    assert "title" in goal and goal["title"]
    assert "deadline" in goal
    assert "daily_minutes" in goal
    assert goal["daily_minutes"] == 120

    # tasks block
    assert "tasks" in body
    assert isinstance(body["tasks"], list)
    assert len(body["tasks"]) >= 1
    for task in body["tasks"]:
        assert "course_name" in task
        assert "title" in task
        assert "task_type" in task
        assert "estimate_minutes" in task
        assert "priority" in task
        assert "acceptance" in task
        # course_name must be reconciled to an actual course
        assert task["course_name"] == "操作系统"

    # todos block
    assert "todos" in body
    assert isinstance(body["todos"], list)
    assert len(body["todos"]) >= 1
    for todo in body["todos"]:
        assert "id" in todo
        assert "task_id" in todo
        assert "course_id" in todo
        assert "title" in todo
        assert "scheduled_date" in todo
        assert "estimate_minutes" in todo
        assert "status" in todo


def test_create_plan_with_stable_course_ids(client) -> None:
    """The preferred contract selects a course by id, even for duplicate names."""
    headers = auth_headers(client, username="alice")
    first_id = create_course(client, headers, "同名课程")
    selected_id = create_course(client, headers, "同名课程")

    resp = client.post(
        "/api/v1/plans",
        json={
            "goal": "完成指定课程",
            "course_ids": [selected_id],
            "deadline": "2026-07-30",
            "daily_minutes": 120,
        },
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert first_id != selected_id
    assert body["tasks"]
    assert {task["course_id"] for task in body["tasks"]} == {selected_id}
    assert {todo["course_id"] for todo in body["todos"]} == {selected_id}


def test_list_and_restore_persisted_plan(client) -> None:
    """A saved plan can be listed with progress and restored in full."""
    headers = auth_headers(client, username="alice")
    created = _create_plan(client, headers)
    goal_id = created["goal"]["id"]
    completed_todo_id = created["todos"][0]["id"]
    complete_resp = client.patch(
        f"/api/v1/todos/{completed_todo_id}",
        json={"status": "completed"},
        headers=headers,
    )
    assert complete_resp.status_code == 200

    list_resp = client.get("/api/v1/plans", headers=headers)
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload["total"] == 1
    summary = payload["items"][0]
    assert summary["goal"]["id"] == goal_id
    assert summary["course_names"] == ["操作系统"]
    assert summary["progress"]["tasks_total"] == len(created["tasks"])
    assert summary["progress"]["todos_total"] == len(created["todos"])
    assert summary["progress"]["todos_completed"] == 1

    detail_resp = client.get(f"/api/v1/plans/{goal_id}", headers=headers)
    assert detail_resp.status_code == 200
    restored = detail_resp.json()
    assert restored["goal"] == created["goal"]
    assert [task["id"] for task in restored["tasks"]] == [
        task["id"] for task in created["tasks"]
    ]
    restored_todo = next(
        todo for todo in restored["todos"] if todo["id"] == completed_todo_id
    )
    assert restored_todo["status"] == "completed"


def test_plan_list_and_detail_are_user_scoped(client) -> None:
    """Another user's saved goal is neither listed nor readable."""
    headers_a = auth_headers(client, username="alice")
    created = _create_plan(client, headers_a)
    goal_id = created["goal"]["id"]

    headers_b = auth_headers(client, username="bob")
    list_resp = client.get("/api/v1/plans", headers=headers_b)
    assert list_resp.status_code == 200
    assert list_resp.json() == {"items": [], "total": 0}

    detail_resp = client.get(f"/api/v1/plans/{goal_id}", headers=headers_b)
    assert detail_resp.status_code == 404

    anonymous_resp = client.get("/api/v1/plans")
    assert anonymous_resp.status_code == 401


def test_list_todos(client) -> None:
    """GET /api/v1/todos?date=YYYY-MM-DD returns the day's todos."""
    headers = auth_headers(client, username="alice")
    body = _create_plan(client, headers)

    todos = body["todos"]
    first_date = todos[0]["scheduled_date"]

    resp = client.get(
        f"/api/v1/todos?date={first_date}",
        headers=headers,
    )
    assert resp.status_code == 200
    payload = resp.json()
    items = payload["items"] if isinstance(payload, dict) else payload
    assert len(items) >= 1
    for item in items:
        assert item["scheduled_date"] == first_date


def test_list_todos_by_status(client) -> None:
    """GET /api/v1/todos?status=pending returns only pending todos."""
    headers = auth_headers(client, username="alice")
    body = _create_plan(client, headers)
    total = len(body["todos"])

    resp = client.get(
        "/api/v1/todos?status=pending",
        headers=headers,
    )
    assert resp.status_code == 200
    payload = resp.json()
    items = payload["items"] if isinstance(payload, dict) else payload
    assert len(items) == total
    for item in items:
        assert item["status"] == "pending"

    # completed filter should be empty before any PATCH
    resp2 = client.get(
        "/api/v1/todos?status=completed",
        headers=headers,
    )
    assert resp2.status_code == 200
    payload2 = resp2.json()
    items2 = payload2["items"] if isinstance(payload2, dict) else payload2
    assert len(items2) == 0


def test_list_todos_honors_pagination_and_keeps_filtered_total(client) -> None:
    """page/page_size slice items while total remains the filtered count."""
    headers = auth_headers(client, username="alice")
    body = _create_plan(client, headers)
    assert len(body["todos"]) >= 2

    first_page = client.get(
        "/api/v1/todos?page=1&page_size=1",
        headers=headers,
    )
    second_page = client.get(
        "/api/v1/todos?page=2&page_size=1",
        headers=headers,
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json()["total"] == len(body["todos"])
    assert second_page.json()["total"] == len(body["todos"])
    assert len(first_page.json()["items"]) == 1
    assert len(second_page.json()["items"]) == 1
    assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]


def test_complete_todo(client) -> None:
    """PATCH /api/v1/todos/{id} {status:"completed"} returns 200."""
    headers = auth_headers(client, username="alice")
    body = _create_plan(client, headers)
    todo_id = body["todos"][0]["id"]

    resp = client.patch(
        f"/api/v1/todos/{todo_id}",
        json={"status": "completed", "actual_minutes": 55},
        headers=headers,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["id"] == todo_id
    assert updated["status"] == "completed"
    assert updated["actual_minutes"] == 55
    assert updated["completed_at"] is not None

    reopened_resp = client.patch(
        f"/api/v1/todos/{todo_id}",
        json={"status": "pending"},
        headers=headers,
    )
    assert reopened_resp.status_code == 200
    reopened = reopened_resp.json()
    assert reopened["status"] == "pending"
    assert reopened["completed_at"] is None


def test_postpone_todo(client) -> None:
    """PATCH /api/v1/todos/{id} {status:"postponed"} returns 200."""
    headers = auth_headers(client, username="alice")
    body = _create_plan(client, headers)
    todo_id = body["todos"][0]["id"]

    resp = client.patch(
        f"/api/v1/todos/{todo_id}",
        json={"status": "postponed"},
        headers=headers,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["id"] == todo_id
    assert updated["status"] == "postponed"


def test_plan_isolation(client) -> None:
    """User B accessing user A's todo returns 404."""
    headers_a = auth_headers(client, username="alice")
    body = _create_plan(client, headers_a)
    todo_id = body["todos"][0]["id"]

    headers_b = auth_headers(client, username="bob")
    resp = client.patch(
        f"/api/v1/todos/{todo_id}",
        json={"status": "completed"},
        headers=headers_b,
    )
    assert resp.status_code == 404

    # GET should also not surface other users' todos
    resp_get = client.get("/api/v1/todos", headers=headers_b)
    assert resp_get.status_code == 200
    payload = resp_get.json()
    items = payload["items"] if isinstance(payload, dict) else payload
    assert len(items) == 0


def test_planner_agent_unit(client) -> None:
    """Unit test: PlannerAgent.generate outputs persistable task JSON."""
    headers = auth_headers(client, username="alice")
    create_course(client, headers, "操作系统")

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        result = planner_generate(
            db=db,
            user_id=1,
            goal="7天复习完操作系统",
            courses=["操作系统"],
            deadline=date(2026, 7, 30),
            daily_minutes=120,
        )
        assert "goal_title" in result
        assert "deadline" in result
        assert "daily_minutes" in result
        assert "tasks" in result
        assert isinstance(result["tasks"], list)
        assert len(result["tasks"]) >= 1
        for task in result["tasks"]:
            assert "course_name" in task
            assert "title" in task
            assert "task_type" in task
            assert "estimate_minutes" in task
            assert "priority" in task
            assert "acceptance" in task
            # course_name reconciled to an actual course
            assert task["course_name"] == "操作系统"
    finally:
        db.close()


def test_scheduler_unit() -> None:
    """Unit test: scheduler outputs daily todos not exceeding daily_minutes."""
    tasks = [
        {
            "title": "复习第一章",
            "course_name": "操作系统",
            "estimate_minutes": 60,
            "priority": 5,
        },
        {
            "title": "完成第二章习题",
            "course_name": "操作系统",
            "estimate_minutes": 60,
            "priority": 4,
        },
        {
            "title": "整理思维导图",
            "course_name": "操作系统",
            "estimate_minutes": 90,
            "priority": 3,
        },
    ]
    start = date(2026, 7, 10)
    deadline = date(2026, 7, 12)
    daily = 120

    scheduled = schedule_tasks(tasks, start, deadline, daily)

    # Every task gets scheduled
    assert len(scheduled) == len(tasks)
    # Each item carries the expected fields
    for item in scheduled:
        assert "task_index" in item
        assert "scheduled_date" in item
        assert "estimate_minutes" in item
        assert "title" in item
        assert "course_name" in item
        assert start <= item["scheduled_date"] <= deadline

    # Daily total must not exceed daily_minutes
    daily_totals: dict[date, int] = defaultdict(int)
    for item in scheduled:
        daily_totals[item["scheduled_date"]] += item["estimate_minutes"]
    for day, total in daily_totals.items():
        assert total <= daily, f"Day {day} exceeds daily_minutes: {total}"

    # High-priority tasks should be scheduled no later than low-priority ones
    by_index = {item["task_index"]: item["scheduled_date"] for item in scheduled}
    assert by_index[0] <= by_index[2]  # priority 5 before priority 3
