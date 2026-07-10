"""Tests for AI-based chunk quality validation."""
from app.models.material_chunk import MaterialChunk
from app.agents.llm import _mock_response, call_llm, _heuristic_quality_score
from app.services.chunk_quality import evaluate_chunks_quality


def test_material_chunk_has_quality_fields():
    """MaterialChunk model should have quality_score and quality_reason columns."""
    assert hasattr(MaterialChunk, "quality_score")
    assert hasattr(MaterialChunk, "quality_reason")
    col = MaterialChunk.__table__.columns.get("quality_score")
    assert col is not None
    assert col.nullable is True


def test_mock_chunk_quality_basic():
    """Mock chunk_quality should return evaluations list with scores."""
    prompt = """请评估以下文档片段的质量：

[片段0]
操作系统是管理计算机硬件资源的系统软件，负责进程调度、内存管理和文件系统。

[片段1]
R1 R2 H1 H2 0 1 0 1
"""
    result = _mock_response("chunk_quality", prompt)
    assert "evaluations" in result
    assert len(result["evaluations"]) == 2
    for ev in result["evaluations"]:
        assert "index" in ev
        assert "quality" in ev
        assert "reason" in ev
        assert 0.0 <= ev["quality"] <= 1.0


def test_mock_chunk_quality_scores_meaningful_content_higher():
    """Meaningful content should get higher score than garbage."""
    prompt = """请评估以下文档片段的质量：

[片段0]
进程是程序在数据集合上的一次执行过程，是系统进行资源分配和调度的基本单位。进程具有动态性、并发性和独立性。

[片段1]
1 0 1 0 R1 H1
2 1 0 1 R2 H2
3 0 1 0 R3 H3
"""
    result = _mock_response("chunk_quality", prompt)
    scores = {ev["index"]: ev["quality"] for ev in result["evaluations"]}
    assert scores[0] > scores[1]


def test_call_llm_chunk_quality_returns_valid():
    """call_llm with chunk_quality agent_type should return valid dict."""
    prompt = "请评估以下文档片段的质量：\n\n[片段0]\n测试内容"
    result = call_llm(prompt, agent_type="chunk_quality")
    assert "evaluations" in result


def test_heuristic_quality_score_meaningful_text():
    """Meaningful text should get high score."""
    text = "操作系统是管理计算机硬件资源的系统软件。它负责进程调度、内存管理和文件系统管理。操作系统的核心功能包括进程管理、存储器管理、设备管理和文件管理。"
    score, reason = _heuristic_quality_score(text)
    assert score >= 0.7
    assert "完整" in reason or "可用" in reason


def test_heuristic_quality_score_garbage_text():
    """Garbage text should get low score."""
    text = "1 0 1 0 R1 H1\n2 1 0 1 R2 H2\n3 0 1 0 R3 H3\n4 1 0 1 R4 H4"
    score, reason = _heuristic_quality_score(text)
    assert score < 0.3


def test_evaluate_chunks_quality_basic():
    """Should return quality scores for all input chunks."""
    chunks = [
        {"text": "操作系统是管理计算机硬件资源的系统软件。它负责进程调度、内存管理和文件系统管理。操作系统的核心功能包括进程管理、存储器管理、设备管理和文件管理。", "index": 0},
        {"text": "R1 R2 H1 H2\n0 1 0 1\n1 0 1 0", "index": 1},
    ]
    results = evaluate_chunks_quality(chunks)
    assert len(results) == 2
    assert results[0]["quality"] > results[1]["quality"]


def test_evaluate_chunks_quality_batching():
    """Should handle batching for large chunk lists."""
    chunks = [
        {"text": f"这是第{i}个测试片段，包含一些有意义的内容。", "index": i}
        for i in range(12)
    ]
    results = evaluate_chunks_quality(chunks)
    assert len(results) == 12
    for r in results:
        assert 0.0 <= r["quality"] <= 1.0


def test_evaluate_chunks_quality_empty():
    """Should return empty list for empty input."""
    results = evaluate_chunks_quality([])
    assert results == []
