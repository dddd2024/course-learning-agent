"""Tests for Task 19 (retrieval visualization) and Task 20 (reliability level).

Strict TDD: these tests are written first and fail until the
CourseQAAgent / chat endpoint / ChatResponse schema are enhanced to
carry ``retrieved_chunks`` (with ``is_cited`` flag) and
``reliability_level``.

Covers:
- POST /chat response includes retrieved_chunks (chunk_id / score / is_cited)
- is_cited flag marks cited chunks true and uncited chunks false
- reliability_level = high / medium / failed per the calculation rules
- GET /agent-runs/{id} retrieve step records query / top_k / items detail
- not_found=true still returns retrieved_chunks (possibly empty)
"""
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.main import app
from app.models.material_chunk import MaterialChunk
from app.tests.conftest import (
    auth_headers,
    setup_course_with_material,
)


# Multi-chapter material so chunking produces multiple chunks (one per
# heading section). Both chapters mention "快表"/"页表" so the
# "什么是快表？" query retrieves more than one chunk — needed to verify
# the is_cited flag differs across chunks.
TLB_TEXT_LONG = (
    "第一章 快表\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
    "TLB 缺失时需要访问内存中的页表，可能导致性能下降。\n"
    "快表的命中率直接影响系统的整体性能。\n"
    "现代处理器通常有多级 TLB，如 L1 TLB 和 L2 TLB。\n"
    "TLB 的容量有限，不能容纳所有页表项。\n"
    "替换策略决定哪些页表项在 TLB 满时被淘汰。\n"
    "常见的替换策略包括 LRU 和随机替换。\n"
    "TLB 刷新发生在上下文切换时，可能导致性能抖动。\n"
    "ASID 技术可以减少不必要的 TLB 刷新。\n"
    "虚拟内存系统通过 TLB 和页表协同工作。\n"
    "TLB 的设计需要在速度和容量之间权衡。\n"
    "硬件 TLB 和软件管理的 TLB 有不同的特点。\n"
    "TLB shootdown 是多核系统中同步 TLB 刷新的机制。\n"
    "TLB 的组织方式包括全相联、组相联和直接映射。\n"
    "不同的组织方式影响命中率和查找速度。\n"
    "\n"
    "第二章 页表\n"
    "页表是操作系统维护虚拟地址到物理地址映射的数据结构，快表缓存常用页表项。\n"
    "多级页表可以节省内存空间。\n"
    "页表的存储和查询是内存管理的基础。\n"
    "一级页表指向二级页表，二级页表指向物理页框。\n"
    "页表项中包含有效位、修改位、访问位等控制信息。\n"
    "有效位指示该页是否在物理内存中。\n"
    "修改位指示该页是否被写入过。\n"
    "访问位指示该页是否被访问过。\n"
    "页表切换时需要刷新 TLB 以避免地址映射错误。\n"
    "上下文切换可能导致 TLB 全部刷新，影响性能。\n"
    "ASID（地址空间标识符）可以避免不必要的 TLB 刷新。\n"
    "页表的层级越多，访问延迟越大。\n"
    "反向页表通过物理页索引查找对应的虚拟页。\n"
    "哈希页表用于处理稀疏地址空间。\n"
    "页表遍历是 TLB 缺失时的最后手段。\n"
    "页表项的格式因架构而异，但基本字段相似。\n"
    "页表的管理是操作系统内存管理的核心功能。\n"
).encode("utf-8")


def _setup_chat(client, headers, content=TLB_TEXT_LONG) -> tuple[int, int]:
    """Create course + material + conversation; return (course_id, conv_id)."""
    course_id, _ = setup_course_with_material(
        client, headers, content=content
    )
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "TLB 答疑"},
        headers=headers,
    )
    return course_id, conv_resp.json()["id"]


def _get_chunk_ids(course_id: int, limit: int = 3) -> list[int]:
    """Fetch actual chunk_ids for a course from the DB (ordered by index)."""
    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        chunks = (
            db.query(MaterialChunk)
            .filter(MaterialChunk.course_id == course_id)
            .order_by(MaterialChunk.chunk_index.asc())
            .limit(limit)
            .all()
        )
        return [c.id for c in chunks]
    finally:
        db.close()


def _get_chunk_quotes(course_id: int, limit: int = 2) -> list[tuple[int, str]]:
    """Return real, non-empty source snippets paired with their chunk ids."""
    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        chunks = (
            db.query(MaterialChunk)
            .filter(MaterialChunk.course_id == course_id)
            .order_by(MaterialChunk.chunk_index.asc())
            .limit(limit)
            .all()
        )
        return [(chunk.id, (chunk.text or "")[:20]) for chunk in chunks]
    finally:
        db.close()


def test_chat_response_includes_retrieved_chunks(
    client, tmp_path, monkeypatch
) -> None:
    """POST /chat response includes retrieved_chunks with chunk_id/score/is_cited."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "retrieved_chunks" in body
    assert isinstance(body["retrieved_chunks"], list)
    assert len(body["retrieved_chunks"]) >= 1
    for item in body["retrieved_chunks"]:
        assert "chunk_id" in item
        assert "score" in item
        assert "is_cited" in item


def test_retrieved_chunks_is_cited_flag(
    client, tmp_path, monkeypatch
) -> None:
    """Cited chunk has is_cited=true; uncited chunks have is_cited=false."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    # Mock call_llm_with_meta with degraded=False so citations are not
    # forced to "weak" status by the degraded-mock override.
    # (EVID-V3-01 filters out weak citations, so we need non-degraded
    # citations for the is_cited flag to work.)
    from app.agents import course_qa as qa_module
    original_call_llm = qa_module.call_llm_with_meta

    def non_degraded_call_llm(prompt, agent_type, schema=None, user_config=None):
        output, meta = original_call_llm(
            prompt, agent_type, schema=schema, user_config=user_config
        )
        meta["degraded"] = False
        return output, meta

    monkeypatch.setattr(
        "app.agents.course_qa.call_llm_with_meta", non_degraded_call_llm
    )

    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    retrieved = body["retrieved_chunks"]
    cited_ids = {c["chunk_id"] for c in body["citations"]}
    # The multi-chapter material should retrieve 2+ chunks.
    assert len(retrieved) >= 2, "test requires multiple retrieved chunks"
    cited_items = [r for r in retrieved if r["is_cited"]]
    uncited_items = [r for r in retrieved if not r["is_cited"]]
    assert len(cited_items) >= 1
    assert len(uncited_items) >= 1
    for item in cited_items:
        assert item["chunk_id"] in cited_ids
    for item in uncited_items:
        assert item["chunk_id"] not in cited_ids


def test_follow_up_retrieval_uses_bounded_conversation_context(
    client, tmp_path, monkeypatch
) -> None:
    """A pronoun follow-up carries the previous concept into retrieval + prompt."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))
    content = (
        "虚拟存储器把部分程序放在外存中。\n"
        "快表 TLB 缓存页表项以加速地址转换。"
    ).encode("utf-8")
    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers, content=content)
    first = client.post(
        "/api/v1/chat",
        json={"course_id": course_id, "conversation_id": conv_id, "question": "什么是虚拟存储器？"},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    from app.services import chat_service
    original_search = chat_service.keyword_search
    original_answer = chat_service.answer_question
    captured: dict[str, str] = {}

    def spy_search(db, cid, query, top_k=12):
        captured["query"] = query
        return original_search(db, cid, query, top_k)

    def spy_answer(*args, **kwargs):
        captured["context"] = kwargs.get("conversation_context", "")
        return original_answer(*args, **kwargs)

    monkeypatch.setattr(chat_service, "keyword_search", spy_search)
    monkeypatch.setattr(chat_service, "answer_question", spy_answer)
    second = client.post(
        "/api/v1/chat",
        json={"course_id": course_id, "conversation_id": conv_id, "question": "它和快表有什么区别？"},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert "虚拟存储器" in captured["query"]
    assert "虚拟存储器" in captured["context"]


def test_reliability_level_high(client, tmp_path, monkeypatch) -> None:
    """citations>=2 with at least one confidence>=0.5 → reliability_level=high."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers)
    chunk_quotes = _get_chunk_quotes(course_id, limit=2)
    assert len(chunk_quotes) >= 2, "test requires at least 2 chunks"

    def mock_call_llm(prompt, agent_type, schema=None, user_config=None):
        return {
            "answer": "快表是页表的高速缓存，加速地址转换。",
            "key_points": ["加速地址转换"],
            "citations": [
                {
                    "chunk_id": chunk_quotes[0][0],
                    "quote_text": chunk_quotes[0][1],
                    "claim_text": "快表是页表的高速缓存，加速地址转换。",
                    "reason": "直接定义",
                    "confidence": 0.9,
                },
                {
                    "chunk_id": chunk_quotes[1][0],
                    "quote_text": chunk_quotes[1][1],
                    "claim_text": "快表是页表的高速缓存，加速地址转换。",
                    "reason": "补充背景",
                    "confidence": 0.7,
                },
            ],
            "not_found": False,
            "follow_up_questions": ["TLB 如何工作？"],
        }, {
            "provider": "mock",
            "fallback_used": False,
            "fallback_reason": None,
        }

    monkeypatch.setattr("app.agents.course_qa.call_llm_with_meta", mock_call_llm)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reliability_level"] == "high"


def test_reliability_level_low_for_degraded_mock(client, tmp_path, monkeypatch) -> None:
    """A mock fallback may show a source, but is never marked verified.

    EVID-V3-01: weak citations from a degraded mock are now filtered out
    entirely. The answer is replaced with an evidence-insufficient message
    and not_found is set to True.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # EVID-V3-01: all citations are weak (degraded mock), so they are
    # filtered out. The answer is replaced with an evidence-insufficient
    # message and not_found is set to True.
    assert len(body["citations"]) == 0
    assert body["not_found"] is True
    assert "证据" in body["answer"] or "不足" in body["answer"]


def test_reliability_level_failed(client, tmp_path, monkeypatch) -> None:
    """not_found=true → reliability_level=failed."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers)

    # Ask a question whose keywords match no chunk → not_found=true.
    # "量子力学" characters do not appear in the TLB material, so
    # keyword_search returns [] and answer_question forces not_found.
    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "量子力学",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["not_found"] is True
    assert body["reliability_level"] == "failed"


def test_audit_retrieve_step_has_detail(
    client, tmp_path, monkeypatch
) -> None:
    """GET /agent-runs/{id} retrieve step input_data has query/top_k, output_data has items."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    # Phase 2 Task B: this test inspects persisted step detail, so the
    # run must record steps even on success (default is "error" only).
    monkeypatch.setattr("app.core.config.settings.AGENT_TRACE_MODE", "always")

    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers)

    chat_resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    run_id = chat_resp.json()["agent_run_id"]
    assert run_id is not None

    detail_resp = client.get(
        f"/api/v1/agent-runs/{run_id}", headers=headers
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    retrieve_step = next(
        s for s in detail["steps"] if s["step_name"] == "retrieve"
    )
    # input_data should carry query and top_k.
    input_data = retrieve_step["input_data"]
    assert "query" in input_data
    assert "top_k" in input_data
    # output_data should carry an items list with chunk detail.
    output_data = retrieve_step["output_data"]
    assert "items" in output_data
    assert isinstance(output_data["items"], list)
    if output_data["items"]:
        item = output_data["items"][0]
        assert "chunk_id" in item
        assert "score" in item
        assert "snippet" in item


def test_no_citations_shows_retrieved_chunks(
    client, tmp_path, monkeypatch
) -> None:
    """not_found=true still returns retrieved_chunks (possibly empty list)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "量子力学",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["not_found"] is True
    # retrieved_chunks is still present in the response (list, maybe empty).
    assert "retrieved_chunks" in body
    assert isinstance(body["retrieved_chunks"], list)
