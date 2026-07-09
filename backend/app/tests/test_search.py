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
    create_course,
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


# T07: 检索质量 — 中英文混合查询 + 标题/材料名加权

MIXED_CN_EN_TEXT = (
    "# 快表原理\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "# 页表机制\n"
    "快表与页表协同工作，实现虚拟内存机制。\n"
).encode("utf-8")

# 标题加权测试内容：章节 A 标题含「快表」但正文无；章节 B 标题不含但正文三次。
# 当前实现（仅正文计分）会让 B 排在前面；加权后 A 应反超。
TITLE_WEIGHT_TEXT = (
    "# 快表\n"
    "TLB 是高速缓存。\n"
    "# 其他章节\n"
    "快表 快表 快表。\n"
).encode("utf-8")


def test_keyword_search_hits_mixed_cn_en(client, tmp_path, monkeypatch) -> None:
    """T07: 中英文混合查询「快表 TLB」能命中相关切块。"""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers, content=MIXED_CN_EN_TEXT
    )

    from app.api.deps import get_db
    from app.main import app

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        results = keyword_search(db, course_id, "快表 TLB", top_k=12)
        assert len(results) > 0
        assert any(
            "快表" in r["text"] or "TLB" in r["text"] for r in results
        )
    finally:
        db.close()


def test_keyword_search_weights_title_higher(client, tmp_path, monkeypatch) -> None:
    """T07: 标题命中加权 3x，使标题含关键词的切块排名高于正文多次命中。

    内容有两个章节：
      - 「# 快表」：标题含「快表」，正文不含「快表」（仅 TLB）
      - 「# 其他章节」：标题不含「快表」，正文含「快表」三次
    当前实现（仅正文计分）：A=1（标题在 text 中）, B=3 → B 胜
    加权后：A = 3*1（标题）+ 1（正文里的标题行）= 4, B = 0 + 3 = 3 → A 胜
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers, content=TITLE_WEIGHT_TEXT
    )

    from app.api.deps import get_db
    from app.main import app

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        results = keyword_search(db, course_id, "快表", top_k=12)
        assert len(results) >= 2
        # 加权后标题含「快表」的切块应排第一
        top = results[0]
        assert "快表" in (top.get("title") or "")
        assert results[0]["score"] > results[1]["score"]
    finally:
        db.close()


def test_keyword_search_weights_filename(client, tmp_path, monkeypatch) -> None:
    """T07: 材料名命中加权 2x，使文件名含关键词的切块排名更高。

    上传两个材料到同一课程，正文都只含「快表」一次：
      - 「快表笔记.txt」：文件名含「快表」
      - 「普通笔记.txt」：文件名不含「快表」
    查询「快表」时，前者的切块 score 应高于后者。
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    from app.tests.conftest import upload_material

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "检索加权测试")

    body_kw = "快表是页表的高速缓存\n".encode("utf-8")

    # 上传并解析两个材料
    mid_a = upload_material(
        client, headers, course_id, "快表笔记.txt", body_kw
    )
    client.post(f"/api/v1/materials/{mid_a}/parse", headers=headers)

    mid_b = upload_material(
        client, headers, course_id, "普通笔记.txt", body_kw
    )
    client.post(f"/api/v1/materials/{mid_b}/parse", headers=headers)

    from app.api.deps import get_db
    from app.main import app

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        results = keyword_search(db, course_id, "快表", top_k=12)
        assert len(results) >= 2
        # 文件名含「快表」的切块应排名更高
        top = results[0]
        assert "快表" in (top.get("filename") or "")
        assert results[0]["score"] > results[1]["score"]
    finally:
        db.close()


# T08: 搜索去重 + 摘要生成

def test_keyword_search_deduplicates_same_page(
    client, tmp_path, monkeypatch
) -> None:
    """T08: 同一页面的多个匹配切块去重，只保留最高分的一个。"""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )

    from app.api.deps import get_db
    from app.main import app
    from app.models.material import Material
    from app.models.material_chunk import MaterialChunk

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        # Add duplicate chunks on the same page (page_no=5) so dedup kicks in
        mat = (
            db.query(Material)
            .filter(Material.course_id == course_id)
            .first()
        )
        if mat:
            for i in range(3):
                db.add(MaterialChunk(
                    material_id=mat.id,
                    course_id=course_id,
                    chunk_index=100 + i,
                    page_no=5,
                    title="TLB缓存",
                    text=f"TLB是Translation Lookaside Buffer的缩写，TLB缓存了页表项。重复内容{i}",
                    keyword_text="TLB Translation Lookaside Buffer 缓存 页表",
                ))
            db.commit()

        results = keyword_search(db, course_id, "TLB", top_k=12)
        assert len(results) >= 1
        # For results with page_no set, no two should share the same
        # (material_id, page_no)
        seen_pages: set = set()
        for r in results:
            if r["page_no"] is None:
                continue  # skip non-PDF chunks
            key = (r["material_id"], r["page_no"])
            assert key not in seen_pages, f"Duplicate page: {key}"
            seen_pages.add(key)
    finally:
        db.close()


def test_keyword_search_includes_snippet(
    client, tmp_path, monkeypatch
) -> None:
    """T08: 搜索结果包含 snippet 字段，为关键词上下文摘要。"""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )

    from app.api.deps import get_db
    from app.main import app

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        results = keyword_search(db, course_id, "TLB", top_k=12)
        assert len(results) >= 1
        for r in results:
            assert "snippet" in r
            assert len(r["snippet"]) <= 200
            assert len(r["snippet"]) > 0
    finally:
        db.close()


def test_generate_snippet_filters_noise() -> None:
    """T08: generate_snippet 过滤噪声行（IP地址、页码、单字母）。"""
    from app.retrieval.search import generate_snippet

    text = (
        "192.168.1.1\n"
        "第3页\n"
        "A YX B Z\n"
        "ARP协议是地址解析协议\n"
        "ARP缓存表存储IP到MAC的映射\n"
        "43\n"
    )
    snippet = generate_snippet(text, ["ARP"])
    assert "ARP" in snippet
    assert "192.168" not in snippet
    assert "第3页" not in snippet


# T09: 知识点数量 + 标题规范化

def test_mock_outline_generates_many_points() -> None:
    """T09: mock outline 应从所有chunk生成知识点，而非仅前10个。"""
    from app.agents.llm import _mock_outline

    chunks = []
    for i in range(20):
        chunks.append(
            f"[片段{i+1}] chunk_id={i+1}，标题：概念{i+1}\n"
            f"这是第{i+1}个知识点的内容。包含重要概念和定义。"
        )
    prompt = "\n\n".join(chunks)
    result = _mock_outline(prompt)
    points = result.get("knowledge_points", [])
    assert len(points) >= 10, f"Expected >= 10 points, got {len(points)}"


def test_normalize_title_converts_questions() -> None:
    """T09: 疑问句标题转换为概念名。"""
    from app.agents.outline import _normalize_title

    assert _normalize_title("为什么需要数据链路层?") == "数据链路层的必要性"
    assert _normalize_title("什么是CSMA/CD协议?") == "CSMA/CD协议"
    assert _normalize_title("虚拟存储器") == "虚拟存储器"
    assert _normalize_title("第10章") == ""
    assert _normalize_title("Date") == ""
    assert _normalize_title("第五章") == ""
