"""Tests for the keyword retrieval module (BE-06).

Strict TDD: these tests are written first and fail until
``app.retrieval.search.keyword_search`` and the ``GET /api/v1/search``
endpoint are implemented.

Covers:
- GET /api/v1/search?course_id=X&keyword=... returns relevant chunks
- Search results are scoped to the given course
- Empty keyword is handled gracefully (empty list)
- top_k limits the number of returned chunks
- Cross-user isolation: searching another user's course returns 404
- Direct unit test of keyword_search(db, course_id, query, top_k)
- No matches returns an empty list
"""
from sqlalchemy.orm import Session

from app.retrieval.search import keyword_search
from app.tests.conftest import (
    auth_headers,
    setup_course_with_material,
)


# Text with multiple chunks worth of content all mentioning "TLB" /
# "快表" / "页表" so we can exercise top_k and relevance scoring.
TLB_TEXT = (
    "操作系统课程笔记。\n"
    "第一章 内存管理。\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
    "页表存储虚拟页到物理页的映射关系，多级页表可以减少内存占用。\n"
    "第二章 地址转换。\n"
    "TLB 缺失时需要访问页表，可能引发缺页中断。\n"
    "快表 TLB 的命中率直接影响地址转换性能。\n"
    "页表项中包含有效位、修改位、访问位等控制信息。\n"
    "第三章 虚拟内存。\n"
    "TLB 与页表协同工作，实现虚拟内存机制。\n"
    "快表 TLB 通常由硬件实现，对操作系统透明。\n"
    "页表切换时需要刷新 TLB 以避免地址映射错误。\n"
).encode("utf-8")


def test_keyword_search_returns_relevant(client, tmp_path, monkeypatch) -> None:
    """GET /search?course_id=X&keyword=TLB returns chunks containing TLB."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )

    resp = client.get(
        f"/api/v1/search?course_id={course_id}&keyword=TLB",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 1
    # Every returned item should contain the keyword "TLB".
    for item in body["items"]:
        assert "text" in item
        assert "TLB" in item["text"] or "TLB" in (item.get("title") or "")
        assert "chunk_id" in item
        assert "material_id" in item
        assert "filename" in item
        assert "score" in item
        assert "page_no" in item


def test_search_filter_by_course(client, tmp_path, monkeypatch) -> None:
    """Searching course A must not return chunks from course B."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_a, _ = setup_course_with_material(
        client, headers, name="操作系统", content=TLB_TEXT
    )
    course_b, _ = setup_course_with_material(
        client, headers, name="计算机组成原理", content=TLB_TEXT
    )

    resp = client.get(
        f"/api/v1/search?course_id={course_a}&keyword=TLB",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    # All returned chunks must belong to course_a.
    for item in body["items"]:
        # course_a's only material's chunks should be returned; we can
        # verify by re-searching course_b and confirming disjoint ids.
        pass

    # Cross-check: get all chunk_ids from course_b's search and ensure
    # they don't overlap with course_a's results.
    resp_b = client.get(
        f"/api/v1/search?course_id={course_b}&keyword=TLB",
        headers=headers,
    )
    ids_a = {item["chunk_id"] for item in body["items"]}
    ids_b = {item["chunk_id"] for item in resp_b.json()["items"]}
    assert ids_a, "course A should have matches"
    assert ids_b, "course B should have matches"
    assert ids_a.isdisjoint(ids_b), "chunks from course B leaked into course A"


def test_search_empty_keyword(client, tmp_path, monkeypatch) -> None:
    """Empty keyword returns an empty list (graceful handling)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers)

    resp = client.get(
        f"/api/v1/search?course_id={course_id}&keyword=",
        headers=headers,
    )
    # Accept either 400 (validation) or 200 with empty list.
    assert resp.status_code in (200, 400)
    if resp.status_code == 200:
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []


def test_search_top_k(client, tmp_path, monkeypatch) -> None:
    """GET /search?top_k=3 returns at most 3 items."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )

    resp = client.get(
        f"/api/v1/search?course_id={course_id}&keyword=TLB&top_k=3",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) <= 3
    # The text has more than 3 chunks mentioning TLB, so we expect exactly 3.
    assert len(body["items"]) == 3


def test_search_isolation(client, tmp_path, monkeypatch) -> None:
    """User B searching user A's course returns 404 (isolation)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers_a = auth_headers(client, username="alice")
    course_id_a, _ = setup_course_with_material(
        client, headers_a, content=TLB_TEXT
    )

    headers_b = auth_headers(client, username="bob")
    resp = client.get(
        f"/api/v1/search?course_id={course_id_a}&keyword=TLB",
        headers=headers_b,
    )
    assert resp.status_code == 404


def test_keyword_search_function(client, tmp_path, monkeypatch) -> None:
    """Unit test: keyword_search returns dicts with required keys."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, material_id = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )

    # Reach into the app's DB session to call keyword_search directly.
    from app.api.deps import get_db
    from app.main import app

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        results = keyword_search(db, course_id, "TLB", top_k=12)
        assert isinstance(results, list)
        assert len(results) >= 1
        for item in results:
            assert set(item.keys()) >= {
                "chunk_id",
                "text",
                "score",
                "page_no",
                "material_id",
                "filename",
            }
            assert item["material_id"] == material_id
            assert "TLB" in item["text"]
            assert isinstance(item["score"], (int, float))
            assert item["score"] > 0
    finally:
        db.close()


def test_search_no_result(client, tmp_path, monkeypatch) -> None:
    """Searching a non-existent keyword returns an empty list."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers)

    resp = client.get(
        f"/api/v1/search?course_id={course_id}&keyword=量子比特超导",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []
