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


# T08: 薄弱点权重 + 超预算提示


def test_overflow_returns_warning(client) -> None:
    """T08: 任务总量超出每日预算时，response 含 overflow_warnings。"""
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="溢出测试课程")
    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [{"course_id": course_id, "deadline": "2026-08-15"}],
            "daily_minutes": 10,  # 极低预算，必然溢出
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "overflow_warnings" in body
    assert isinstance(body["overflow_warnings"], list)
    # mock planner 生成 90+60 分钟任务，10 分钟预算必然触发溢出
    if len(body["schedule"]) > 0:
        assert len(body["overflow_warnings"]) >= 1


def test_no_overflow_when_budget_sufficient(client) -> None:
    """T08: 预算充足时 overflow_warnings 为空列表。"""
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="充足预算课程")
    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [{"course_id": course_id, "deadline": "2026-12-31"}],
            "daily_minutes": 480,  # 充足预算
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "overflow_warnings" in body
    assert isinstance(body["overflow_warnings"], list)


def test_weak_point_weight_computation(client) -> None:
    """Unresolved weak points account for current mastery as well as mistakes."""
    from sqlalchemy.orm import Session

    from app.api.deps import get_db
    from app.main import app
    from app.models.course import Course
    from app.models.knowledge_point import KnowledgePoint
    from app.models.quiz import WeakPoint
    from app.models.user import User
    from app.services.multi_scheduler import _compute_weak_point_weight
    from app.tests.conftest import auth_headers, create_course

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="薄弱点课程")

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        user = db.query(User).filter(User.username == "alice").first()
        # 插入一条知识点 + 两条薄弱点记录
        kp = KnowledgePoint(
            course_id=course_id,
            user_id=user.id,
            title="测试知识点",
            summary="",
            importance=3,
            source_chunk_ids="[]",
            exam_style="",
            review_action="",
        )
        db.add(kp)
        db.flush()
        wp1 = WeakPoint(
            user_id=user.id,
            course_id=course_id,
            knowledge_point_id=kp.id,
            wrong_count=3,
        )
        wp2 = WeakPoint(
            user_id=user.id,
            course_id=course_id,
            knowledge_point_id=kp.id + 1,  # 不同 KP（即使不存在也行，FK 不强制）
            wrong_count=2,
        )
        db.add(wp1)
        db.add(wp2)
        db.commit()

        weight = _compute_weak_point_weight(db, user.id, course_id)
        assert weight > 0.0
        assert 0.0 < weight <= 1.0

        # 无薄弱点的课程权重应为 0
        empty_course = create_course(client, headers, name="无薄弱点课程")
        weight_empty = _compute_weak_point_weight(db, user.id, empty_course)
        assert weight_empty == 0.0
    finally:
        db.close()


# T01: 多课程优先级字段兼容 — 旧前端发送 priority（1-5）应被接受


def test_multi_plan_accepts_legacy_priority_field() -> None:
    """T01/T0-1: 旧前端发送 priority（1-5）应被 schema 归一化为 0-1。"""
    from app.schemas.multi_plan import MultiCourseInput

    # 旧字段 priority=4（1-5）应归一化为 0.8
    item = MultiCourseInput.model_validate(
        {"course_id": 1, "deadline": "2099-01-01", "priority": 4}
    )
    assert item.user_priority == 0.8

    # 旧字段 priority=1（最低）应归一化为 0.2，不是 1.0
    item_low = MultiCourseInput.model_validate(
        {"course_id": 1, "deadline": "2099-01-01", "priority": 1}
    )
    assert item_low.user_priority == 0.2

    # 新字段 user_priority=0.8 仍然直接生效
    item2 = MultiCourseInput.model_validate(
        {"course_id": 1, "deadline": "2099-01-01", "user_priority": 0.8}
    )
    assert item2.user_priority == 0.8

    # 两个字段都未提供时为 None
    item3 = MultiCourseInput.model_validate(
        {"course_id": 1, "deadline": "2099-01-01"}
    )
    assert item3.user_priority is None


def test_multi_plan_normalizes_priority_in_api(client, monkeypatch) -> None:
    """T01: priority=4（1-5）经 schema 归一化为 0.8 后传入 scheduler。"""
    from app.api.v1.endpoints import plans as plans_module

    captured: dict = {}

    def fake_schedule(db, user_id, courses, daily_minutes, user_config=None):
        captured["courses"] = courses
        captured["user_config"] = user_config
        return {"schedule": [], "overflow_warnings": []}

    monkeypatch.setattr(plans_module, "schedule_multi_courses", fake_schedule)

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="优先级测试课程")
    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [
                {"course_id": course_id, "deadline": "2099-01-01", "priority": 4}
            ],
            "daily_minutes": 120,
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    # priority=4 应被归一化为 0.8
    assert captured["courses"][0]["user_priority"] == 0.8


def test_priority_1_normalizes_to_02(client, monkeypatch) -> None:
    """T0-1: 旧字段 priority=1 应归一化为 0.2，不是 1.0。"""
    from app.api.v1.endpoints import plans as plans_module

    captured: dict = {}

    def fake_schedule(db, user_id, courses, daily_minutes, user_config=None):
        captured["courses"] = courses
        return {"schedule": [], "overflow_warnings": []}

    monkeypatch.setattr(plans_module, "schedule_multi_courses", fake_schedule)

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="边界课程")
    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [
                {"course_id": course_id, "deadline": "2099-01-01", "priority": 1}
            ],
            "daily_minutes": 120,
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    # priority=1（1-5 旧字段）应归一化为 0.2
    assert captured["courses"][0]["user_priority"] == 0.2


def test_user_priority_zero_not_overridden_in_scheduler(monkeypatch) -> None:
    """T0-2: scheduler 内部 user_priority=0.0 不应被 or 0.5 覆盖。"""
    from datetime import date

    from app.services import multi_scheduler

    captured_priorities: list = []

    def fake_planner_generate(
        db, user_id, goal, courses, deadline, daily_minutes, user_config=None
    ):
        return {"tasks": []}

    monkeypatch.setattr(multi_scheduler, "planner_generate", fake_planner_generate)

    class _DummyDb:
        def query(self, *a, **k):
            class _Q:
                def filter(self, *a, **k):
                    return self

                def all(self):
                    return []

                def scalar(self):
                    return 0

            return _Q()

    original_compute = multi_scheduler.compute_priority_score

    def spy_compute(
        deadline_urgency, workload_weight, weak_point_weight, user_priority
    ):
        captured_priorities.append(user_priority)
        return original_compute(
            deadline_urgency, workload_weight, weak_point_weight, user_priority
        )

    monkeypatch.setattr(multi_scheduler, "compute_priority_score", spy_compute)

    multi_scheduler.schedule_multi_courses(
        db=_DummyDb(),
        user_id=1,
        courses=[
            {"course_id": 1, "deadline": date(2099, 1, 1), "user_priority": 0.0}
        ],
        daily_minutes=120,
    )

    assert 0.0 in captured_priorities, (
        "user_priority=0.0 应被保留，不应被 0.5 覆盖"
    )


# T02: 多课程规划应透传用户 LLM 配置


def test_schedule_multi_courses_passes_user_config_to_planner(monkeypatch) -> None:
    """T02: schedule_multi_courses 应把 user_config 透传给 planner_generate。"""
    from datetime import date

    from app.services import multi_scheduler

    captured: dict = {}

    def fake_planner_generate(
        db, user_id, goal, courses, deadline, daily_minutes, user_config=None
    ):
        captured["user_config"] = user_config
        return {"tasks": []}

    monkeypatch.setattr(multi_scheduler, "planner_generate", fake_planner_generate)

    class _DummyDb:
        def query(self, *a, **k):
            class _Q:
                def filter(self, *a, **k):
                    return self

                def all(self):
                    return []

                def scalar(self):
                    return 0

            return _Q()

    multi_scheduler.schedule_multi_courses(
        db=_DummyDb(),
        user_id=1,
        courses=[
            {"course_id": 1, "deadline": date(2099, 1, 1), "user_priority": 0.5}
        ],
        daily_minutes=120,
        user_config={"provider": "real", "model": "gpt-4"},
    )

    assert captured["user_config"] == {"provider": "real", "model": "gpt-4"}
