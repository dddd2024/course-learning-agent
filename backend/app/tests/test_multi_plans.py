"""Tests for the multi-course planning module (BE-11, AG-06).

Strict TDD: these tests are written first and fail until the
``MultiCourseScheduler`` service, ``POST /plans/multi`` endpoint, and
their schemas are implemented.

Covers:
- POST /api/v1/plans/multi (schedule tasks across multiple courses)
- Per-day total <= daily_minutes constraint
- Per-course-per-day <= 90 minutes constraint (split if exceeded)
- Cross-user course access returns 404
- compute_priority_score unit test
- Persistence of generated todos
"""
from collections import defaultdict

from app.services.multi_scheduler import compute_priority_score
from app.tests.conftest import auth_headers, create_course


def _create_two_courses(client, headers) -> list[dict]:
    """Create two courses and return [{course_id, deadline}, ...]."""
    course_a = create_course(client, headers, name="机器学习")
    course_b = create_course(client, headers, name="数据结构")
    return [
        {"course_id": course_a, "deadline": "2026-07-30"},
        {"course_id": course_b, "deadline": "2026-07-30"},
    ]


def test_create_multi_plan(client) -> None:
    """POST /api/v1/plans/multi returns 200 with schedule covering both courses."""
    headers = auth_headers(client, username="alice")
    courses = _create_two_courses(client, headers)

    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": courses,
            "daily_minutes": 120,
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "schedule" in body
    assert isinstance(body["schedule"], list)
    assert len(body["schedule"]) >= 1

    # schedule is sorted by date ascending
    dates = [item["scheduled_date"] for item in body["schedule"]]
    assert dates == sorted(dates)

    # both courses should appear in the schedule
    course_names = {item["course_name"] for item in body["schedule"]}
    assert "机器学习" in course_names
    assert "数据结构" in course_names

    # each item carries the expected fields
    for item in body["schedule"]:
        assert "scheduled_date" in item
        assert "course_name" in item
        assert "title" in item
        assert "estimate_minutes" in item


def test_multi_plan_daily_limit(client) -> None:
    """Per-day total minutes across all courses must not exceed daily_minutes."""
    headers = auth_headers(client, username="alice")
    courses = _create_two_courses(client, headers)

    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": courses,
            "daily_minutes": 120,
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    daily_totals: dict[str, int] = defaultdict(int)
    for item in body["schedule"]:
        daily_totals[item["scheduled_date"]] += item["estimate_minutes"]
    for day, total in daily_totals.items():
        assert total <= 120, f"Day {day} exceeds daily_minutes: {total}"


def test_multi_plan_90min_split(client) -> None:
    """Per-course-per-day total must not exceed 90 minutes; split if exceeded."""
    headers = auth_headers(client, username="alice")
    # Single course so the per-course-per-day limit is the binding constraint.
    # Mock planner returns 90 min + 60 min tasks (150 min total).
    course_id = create_course(client, headers, name="机器学习")
    courses = [{"course_id": course_id, "deadline": "2026-08-15"}]

    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": courses,
            "daily_minutes": 240,  # high so 90min rule is the limit
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Per-course per-day total <= 90
    per_course_day: dict[tuple, int] = defaultdict(int)
    for item in body["schedule"]:
        key = (item["course_name"], item["scheduled_date"])
        per_course_day[key] += item["estimate_minutes"]
    for (cname, day), total in per_course_day.items():
        assert total <= 90, (
            f"Course {cname} on {day} exceeds 90 min continuous limit: {total}"
        )

    # Mock returns 90 + 60 min tasks (150 min total). With per-course-per-day
    # capped at 90, the 60-min task must land on a different day than the
    # 90-min task, so at least 2 distinct days are used.
    days_used = {item["scheduled_date"] for item in body["schedule"]}
    assert len(days_used) >= 2


def test_multi_plan_isolation(client) -> None:
    """User B using User A's course returns 404."""
    headers_a = auth_headers(client, username="alice")
    course_id_a = create_course(client, headers_a, name="机器学习")

    headers_b = auth_headers(client, username="bob")
    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [{"course_id": course_id_a, "deadline": "2026-07-30"}],
            "daily_minutes": 120,
            "constraints": {},
        },
        headers=headers_b,
    )
    assert resp.status_code == 404


def test_priority_score() -> None:
    """Unit test: priority_score = deadline*0.45 + workload*0.30
    + weak_point*0.15 + user_priority*0.10."""
    score = compute_priority_score(0.5, 0.4, 0.2, 0.8)
    expected = 0.5 * 0.45 + 0.4 * 0.30 + 0.2 * 0.15 + 0.8 * 0.10
    assert abs(score - expected) < 1e-9

    # Higher deadline urgency yields higher score (other inputs equal).
    s_low = compute_priority_score(0.1, 0.4, 0.2, 0.8)
    s_high = compute_priority_score(0.9, 0.4, 0.2, 0.8)
    assert s_high > s_low

    # Higher workload weight yields higher score.
    s_low_w = compute_priority_score(0.5, 0.1, 0.2, 0.8)
    s_high_w = compute_priority_score(0.5, 0.9, 0.2, 0.8)
    assert s_high_w > s_low_w


def test_multi_plan_persisted(client) -> None:
    """Generated schedule items are persisted to the todos table."""
    headers = auth_headers(client, username="alice")
    courses = _create_two_courses(client, headers)

    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": courses,
            "daily_minutes": 120,
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    schedule_count = len(body["schedule"])

    # GET /todos should now surface the persisted todos.
    resp_todos = client.get("/api/v1/todos", headers=headers)
    assert resp_todos.status_code == 200
    payload = resp_todos.json()
    items = payload["items"] if isinstance(payload, dict) else payload
    assert len(items) >= schedule_count

    # All todos belong to one of the two courses.
    valid_names = {"机器学习", "数据结构"}
    for item in items:
        assert item["course_name"] in valid_names
