"""Tests for the knowledge points module and OutlineAgent (BE-09, AG-05).

Strict TDD: these tests are written first and fail until the
``KnowledgePoint`` model, ``OutlineAgent``, knowledge-points router,
and their schemas are implemented.

Covers:
- POST /api/v1/courses/{id}/knowledge-points/generate (generate KPs)
- GET  /api/v1/courses/{id}/knowledge-points (list, user-scoped)
- Cross-user isolation (404)
- OutlineAgent.generate(db, course_id) unit test (structured output)
- importance calculation unit test (llm + rule adjustments)
- Persistence to the knowledge_points table
"""
from sqlalchemy.orm import Session

from app.agents.outline import calculate_importance, generate
from app.api.deps import get_db
from app.main import app
from app.models.knowledge_point import KnowledgePoint
from app.tests.conftest import (
    auth_headers,
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


def test_generate_knowledge_points(client, tmp_path, monkeypatch) -> None:
    """POST /courses/{id}/knowledge-points/generate returns 200 with KP list."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    resp = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "knowledge_points" in body
    assert isinstance(body["knowledge_points"], list)
    assert len(body["knowledge_points"]) >= 1
    for kp in body["knowledge_points"]:
        assert "title" in kp
        assert "summary" in kp
        assert "importance" in kp
        assert "source_chunk_ids" in kp
        assert "exam_style" in kp
        assert "review_action" in kp
        assert isinstance(kp["source_chunk_ids"], list)
        assert len(kp["source_chunk_ids"]) >= 1


def test_list_knowledge_points(client, tmp_path, monkeypatch) -> None:
    """GET /courses/{id}/knowledge-points returns the persisted list."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )

    resp = client.get(
        f"/api/v1/courses/{course_id}/knowledge-points",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    items = body["items"] if isinstance(body, dict) else body
    assert len(items) >= 1
    for kp in items:
        assert "title" in kp
        assert "summary" in kp
        assert "importance" in kp
        assert "source_chunk_ids" in kp
        assert "exam_style" in kp
        assert "review_action" in kp


def test_generate_isolation(client, tmp_path, monkeypatch) -> None:
    """User B generating KPs for user A's course returns 404."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers_a = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers_a, content=TLB_TEXT
    )

    headers_b = auth_headers(client, username="bob")
    resp = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers_b,
    )
    assert resp.status_code == 404


def test_outline_agent_unit(client, tmp_path, monkeypatch) -> None:
    """Unit test: OutlineAgent.generate returns structured knowledge points."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        result = generate(db, course_id)
        assert isinstance(result, list)
        assert len(result) >= 1
        for kp in result:
            assert "title" in kp
            assert "summary" in kp
            assert "importance" in kp
            assert "source_chunk_ids" in kp
            assert "exam_style" in kp
            assert "review_action" in kp
            assert isinstance(kp["importance"], int)
            assert 1 <= kp["importance"] <= 5
            assert isinstance(kp["source_chunk_ids"], list)
            assert len(kp["source_chunk_ids"]) >= 1
    finally:
        db.close()


def test_importance_calculation() -> None:
    """Unit test: importance combines llm_importance + rule adjustments."""
    chunks = [
        {"chunk_id": 1, "material_id": 1, "text": "..."},
        {"chunk_id": 2, "material_id": 1, "text": "..."},
        {"chunk_id": 3, "material_id": 2, "text": "..."},
    ]
    # Base case: llm_importance=3, no keywords, single material -> 3
    assert calculate_importance(3, "普通知识点", [1, 2], chunks) == 3
    # Title with "重点" -> +1
    assert calculate_importance(3, "重点知识点", [1, 2], chunks) == 4
    # Multiple materials -> +1
    assert calculate_importance(3, "普通知识点", [1, 3], chunks) == 4
    # Both bonuses -> +2
    assert calculate_importance(3, "重点考试知识点", [1, 3], chunks) == 5
    # Cap at 5
    assert calculate_importance(5, "重点考试例题", [1, 3], chunks) == 5


def test_knowledge_points_persisted(client, tmp_path, monkeypatch) -> None:
    """Generated KPs are persisted to the knowledge_points table."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    resp = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )
    assert resp.status_code == 200
    generated = resp.json()["knowledge_points"]
    assert len(generated) >= 1

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        rows = (
            db.query(KnowledgePoint)
            .filter(KnowledgePoint.course_id == course_id)
            .all()
        )
        assert len(rows) == len(generated)
        for row in rows:
            assert row.title
            assert row.summary
            assert 1 <= row.importance <= 5
            assert row.source_chunk_ids  # JSON string
            assert row.exam_style
            assert row.review_action
    finally:
        db.close()
