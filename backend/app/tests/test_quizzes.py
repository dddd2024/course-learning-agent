"""Tests for the quiz and weak-point module (BE-??, AG-07).

Strict TDD: these tests are written first and fail until the
``Quiz`` / ``QuizItem`` / ``WeakPoint`` models, ``QuizAgent``,
quizzes router, and their schemas are implemented.

Covers:
- POST /api/v1/quizzes (generate quiz from knowledge points)
- GET  /api/v1/quizzes (list, user-scoped)
- GET  /api/v1/quizzes/{id} (detail, no answer leaked)
- POST /api/v1/quizzes/{id}/submit (grade + weak-point recording)
- GET  /api/v1/courses/{course_id}/weak-points (list weak points)
- Cross-user isolation (404)
- Planner integration: weak-point review tasks appear in new plans
"""
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.main import app
from app.models.quiz import QuizItem, WeakPoint
from app.tests.conftest import (
    auth_headers,
    create_course,
    setup_course_with_material,
)

# Material content that mentions "快表 TLB 存储管理" so keyword retrieval
# and the outline agent have meaningful chunks to work with.
TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
).encode("utf-8")


def _setup_course_with_kps(
    client,
    headers: dict[str, str],
    content: bytes = TLB_TEXT,
    name: str = "操作系统",
) -> int:
    """Create course + material + generate knowledge points.

    Returns the course_id ready for quiz generation.
    """
    course_id, _ = setup_course_with_material(
        client, headers, name=name, content=content
    )
    resp = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return course_id


def _get_db_session() -> Session:
    """Return a session from the test DB override."""
    db_generator = app.dependency_overrides[get_db]()
    return next(db_generator)


def _get_quiz_item_answers(quiz_id: int) -> list[tuple[int, str, int | None]]:
    """Fetch (item_id, answer, knowledge_point_id) for each item in a quiz.

    Used by submit tests to construct correct / wrong submissions without
    depending on the exact mock LLM output.
    """
    db = _get_db_session()
    try:
        items = (
            db.query(QuizItem)
            .filter(QuizItem.quiz_id == quiz_id)
            .order_by(QuizItem.order_index.asc())
            .all()
        )
        return [
            (item.id, item.answer, item.knowledge_point_id) for item in items
        ]
    finally:
        db.close()


def _count_weak_points(course_id: int) -> int:
    """Return the number of weak-point rows for a course in the test DB."""
    db = _get_db_session()
    try:
        return (
            db.query(WeakPoint)
            .filter(WeakPoint.course_id == course_id)
            .count()
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /quizzes
# ---------------------------------------------------------------------------


def test_create_quiz_success(client, tmp_path, monkeypatch) -> None:
    """POST /quizzes returns 200 with items, no answer field leaked."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers)

    resp = client.post(
        "/api/v1/quizzes",
        json={"course_id": course_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["course_id"] == course_id
    assert body["status"] == "draft"
    assert body["question_count"] >= 1
    assert isinstance(body["items"], list)
    assert len(body["items"]) > 0
    for item in body["items"]:
        # answer must NOT be leaked in the response
        assert "answer" not in item
        assert "question_type" in item
        assert "question_text" in item
        assert "options" in item
        assert "explanation" in item
        assert "order_index" in item


def test_create_quiz_no_knowledge_points(client, tmp_path, monkeypatch) -> None:
    """Course without knowledge points: POST /quizzes returns 4xx or empty items."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    # Create a course but do NOT generate knowledge points.
    course_id = create_course(client, headers, name="空课程")

    resp = client.post(
        "/api/v1/quizzes",
        json={"course_id": course_id},
        headers=headers,
    )
    # Either a 4xx error or a 200 with empty items is acceptable.
    assert resp.status_code >= 400 or (
        resp.status_code == 200 and len(resp.json().get("items", [])) == 0
    )


def test_create_quiz_unauthorized_course(client, tmp_path, monkeypatch) -> None:
    """Other user's course returns 404."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers_a = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers_a)

    headers_b = auth_headers(client, username="bob")
    resp = client.post(
        "/api/v1/quizzes",
        json={"course_id": course_id},
        headers=headers_b,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /quizzes
# ---------------------------------------------------------------------------


def test_list_quizzes(client, tmp_path, monkeypatch) -> None:
    """GET /quizzes returns the current user's quiz list."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers)
    client.post(
        "/api/v1/quizzes", json={"course_id": course_id}, headers=headers
    )

    resp = client.get("/api/v1/quizzes", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    items = body.get("items", body) if isinstance(body, dict) else body
    assert len(items) >= 1
    for quiz in items:
        assert "id" in quiz
        assert "course_id" in quiz
        assert "title" in quiz
        assert "status" in quiz


def test_list_quizzes_filtered_by_course(client, tmp_path, monkeypatch) -> None:
    """GET /quizzes?course_id=X only returns quizzes for that course."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id_a = _setup_course_with_kps(client, headers, name="课程A")
    course_id_b = _setup_course_with_kps(client, headers, name="课程B")

    client.post(
        "/api/v1/quizzes", json={"course_id": course_id_a}, headers=headers
    )
    client.post(
        "/api/v1/quizzes", json={"course_id": course_id_b}, headers=headers
    )

    resp = client.get(
        f"/api/v1/quizzes?course_id={course_id_a}", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    items = body.get("items", body) if isinstance(body, dict) else body
    assert len(items) == 1
    assert items[0]["course_id"] == course_id_a


# ---------------------------------------------------------------------------
# GET /quizzes/{id}
# ---------------------------------------------------------------------------


def test_get_quiz_detail(client, tmp_path, monkeypatch) -> None:
    """GET /quizzes/{id} returns the quiz detail without answers."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers)
    create_resp = client.post(
        "/api/v1/quizzes", json={"course_id": course_id}, headers=headers
    )
    quiz_id = create_resp.json()["id"]

    resp = client.get(f"/api/v1/quizzes/{quiz_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == quiz_id
    assert len(body["items"]) > 0
    for item in body["items"]:
        assert "answer" not in item


def test_get_quiz_detail_unauthorized(client, tmp_path, monkeypatch) -> None:
    """GET /quizzes/{id} for another user's quiz returns 404."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers_a = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers_a)
    create_resp = client.post(
        "/api/v1/quizzes", json={"course_id": course_id}, headers=headers_a
    )
    quiz_id = create_resp.json()["id"]

    headers_b = auth_headers(client, username="bob")
    resp = client.get(f"/api/v1/quizzes/{quiz_id}", headers=headers_b)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /quizzes/{id}/submit
# ---------------------------------------------------------------------------


def test_submit_quiz_correct(client, tmp_path, monkeypatch) -> None:
    """All correct: score == total, no weak_points written."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers)
    create_resp = client.post(
        "/api/v1/quizzes", json={"course_id": course_id}, headers=headers
    )
    quiz_id = create_resp.json()["id"]

    item_answers = _get_quiz_item_answers(quiz_id)
    payload = {
        "answers": [
            {"item_id": item_id, "user_answer": answer}
            for item_id, answer, _ in item_answers
        ]
    }

    resp = client.post(
        f"/api/v1/quizzes/{quiz_id}/submit", json=payload, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["score"] == body["total"]
    assert body["total"] == len(item_answers)

    # No weak points should have been created.
    assert _count_weak_points(course_id) == 0


def test_submit_quiz_wrong(client, tmp_path, monkeypatch) -> None:
    """One wrong: score < total, weak_points has a record."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers)
    create_resp = client.post(
        "/api/v1/quizzes", json={"course_id": course_id}, headers=headers
    )
    quiz_id = create_resp.json()["id"]

    item_answers = _get_quiz_item_answers(quiz_id)
    # Submit first item wrong, the rest correct.
    answers = []
    for i, (item_id, answer, _) in enumerate(item_answers):
        if i == 0:
            answers.append(
                {"item_id": item_id, "user_answer": "DEFINITELY_WRONG_XYZ"}
            )
        else:
            answers.append({"item_id": item_id, "user_answer": answer})

    resp = client.post(
        f"/api/v1/quizzes/{quiz_id}/submit",
        json={"answers": answers},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["score"] < body["total"]

    # The first item's knowledge_point_id (if present) should be in weak_points.
    first_kp_id = item_answers[0][2]
    if first_kp_id is not None:
        assert _count_weak_points(course_id) >= 1
        db = _get_db_session()
        try:
            wp = (
                db.query(WeakPoint)
                .filter(
                    WeakPoint.course_id == course_id,
                    WeakPoint.knowledge_point_id == first_kp_id,
                )
                .first()
            )
            assert wp is not None
            assert wp.wrong_count == 1
        finally:
            db.close()


def test_submit_quiz_wrong_twice_increments(
    client, tmp_path, monkeypatch
) -> None:
    """Same knowledge point wrong twice: wrong_count == 2."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers)

    # First quiz: submit with first item wrong.
    create_resp_1 = client.post(
        "/api/v1/quizzes", json={"course_id": course_id}, headers=headers
    )
    quiz_id_1 = create_resp_1.json()["id"]
    item_answers_1 = _get_quiz_item_answers(quiz_id_1)
    first_kp_id = item_answers_1[0][2]

    answers_1 = [
        {"item_id": item_id, "user_answer": "WRONG_ANSWER_1"}
        for item_id, _, _ in item_answers_1
    ]
    client.post(
        f"/api/v1/quizzes/{quiz_id_1}/submit",
        json={"answers": answers_1},
        headers=headers,
    )

    # Second quiz: submit with first item wrong again (same KP).
    create_resp_2 = client.post(
        "/api/v1/quizzes", json={"course_id": course_id}, headers=headers
    )
    quiz_id_2 = create_resp_2.json()["id"]
    item_answers_2 = _get_quiz_item_answers(quiz_id_2)

    answers_2 = [
        {"item_id": item_id, "user_answer": "WRONG_ANSWER_2"}
        for item_id, _, _ in item_answers_2
    ]
    client.post(
        f"/api/v1/quizzes/{quiz_id_2}/submit",
        json={"answers": answers_2},
        headers=headers,
    )

    if first_kp_id is not None:
        db = _get_db_session()
        try:
            wp = (
                db.query(WeakPoint)
                .filter(
                    WeakPoint.course_id == course_id,
                    WeakPoint.knowledge_point_id == first_kp_id,
                )
                .first()
            )
            assert wp is not None
            assert wp.wrong_count == 2
        finally:
            db.close()


def test_submit_quiz_unauthorized(client, tmp_path, monkeypatch) -> None:
    """Submitting another user's quiz returns 404."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers_a = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers_a)
    create_resp = client.post(
        "/api/v1/quizzes", json={"course_id": course_id}, headers=headers_a
    )
    quiz_id = create_resp.json()["id"]

    headers_b = auth_headers(client, username="bob")
    resp = client.post(
        f"/api/v1/quizzes/{quiz_id}/submit",
        json={"answers": []},
        headers=headers_b,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /courses/{course_id}/weak-points
# ---------------------------------------------------------------------------


def test_get_weak_points(client, tmp_path, monkeypatch) -> None:
    """GET /courses/{id}/weak-points returns the user's weak points."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers)

    # Create a quiz and submit with wrong answers to generate weak points.
    create_resp = client.post(
        "/api/v1/quizzes", json={"course_id": course_id}, headers=headers
    )
    quiz_id = create_resp.json()["id"]
    item_answers = _get_quiz_item_answers(quiz_id)
    answers = [
        {"item_id": item_id, "user_answer": "WRONG"}
        for item_id, _, _ in item_answers
    ]
    client.post(
        f"/api/v1/quizzes/{quiz_id}/submit",
        json={"answers": answers},
        headers=headers,
    )

    resp = client.get(
        f"/api/v1/courses/{course_id}/weak-points", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    items = body.get("items", body) if isinstance(body, dict) else body
    assert len(items) >= 1
    for wp in items:
        assert "id" in wp
        assert "course_id" in wp
        assert "knowledge_point_id" in wp
        assert "knowledge_point_title" in wp
        assert "wrong_count" in wp


def test_weak_point_unauthorized(client, tmp_path, monkeypatch) -> None:
    """Other user's course weak-points returns 404."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers_a = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers_a)

    headers_b = auth_headers(client, username="bob")
    resp = client.get(
        f"/api/v1/courses/{course_id}/weak-points", headers=headers_b
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Planner integration: weak-point review tasks in new plans
# ---------------------------------------------------------------------------


def test_plan_includes_weak_point_review(client, tmp_path, monkeypatch) -> None:
    """Plan generation adds review tasks for the user's weak points."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = _setup_course_with_kps(client, headers, name="操作系统")

    # Create a quiz and submit all wrong to populate weak points.
    create_resp = client.post(
        "/api/v1/quizzes", json={"course_id": course_id}, headers=headers
    )
    quiz_id = create_resp.json()["id"]
    item_answers = _get_quiz_item_answers(quiz_id)
    answers = [
        {"item_id": item_id, "user_answer": "WRONG"}
        for item_id, _, _ in item_answers
    ]
    submit_resp = client.post(
        f"/api/v1/quizzes/{quiz_id}/submit",
        json={"answers": answers},
        headers=headers,
    )
    assert submit_resp.status_code == 200

    # Generate a plan for the same course; it should include at least one
    # weak-point review task with boosted priority.
    plan_resp = client.post(
        "/api/v1/plans",
        json={
            "goal": "复习操作系统",
            "courses": ["操作系统"],
            "deadline": "2026-07-30",
            "daily_minutes": 120,
        },
        headers=headers,
    )
    assert plan_resp.status_code == 200, plan_resp.text
    tasks = plan_resp.json()["tasks"]
    weak_point_tasks = [
        t for t in tasks if "薄弱点" in t.get("title", "")
    ]
    assert len(weak_point_tasks) >= 1
    for t in weak_point_tasks:
        assert t["priority"] >= 4
