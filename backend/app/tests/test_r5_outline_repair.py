from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.outline import OutlineContractError, _cluster_merge_titles, _reconcile_chunk_ids, evaluate_outline_contract, generate


CHUNKS = [
    {"chunk_id": 1, "material_id": 1, "text": "CRC 用于差错检测。", "title": "成帧与差错检测"},
    {"chunk_id": 2, "material_id": 1, "text": "停止等待协议等待确认。", "title": "停止等待协议"},
    {"chunk_id": 3, "material_id": 1, "text": "滑动窗口允许多个帧在途。", "title": "滑动窗口协议"},
]
REAL_META = {
    "meta_observed": True,
    "actual_provider": "user",
    "actual_model": "real-model",
    "fallback_used": False,
    "degraded": False,
}


def _point(title: str, chunk_id: int) -> dict:
    quote = next(chunk["text"] for chunk in CHUNKS if chunk["chunk_id"] == chunk_id)
    return {"title": title, "summary": title, "importance": 3, "source_chunk_ids": [chunk_id], "source_evidence": [{"chunk_id": chunk_id, "quote_text": quote}], "exam_style": "解释", "review_action": "复习"}


def test_outline_contract_detects_number_only_duplicate_titles() -> None:
    result = evaluate_outline_contract([_point("1. CRC 差错检测", 1), _point("2. CRC 差错检测", 2)], CHUNKS)
    assert result["valid_count"] == 2
    assert result["duplicate_title_count"] == 1
    assert result["passed"] is False


def test_outline_canonicalizes_only_exact_numeric_source_ids() -> None:
    assert _reconcile_chunk_ids(["1", "chunk_id=2", "chunk_id_2", 2, "missing", "1"], [1, 2]) == [1, 2]


def test_outline_keeps_same_prefix_points_with_distinct_sources() -> None:
    points = [_point("数据链路层：CRC", 1), _point("数据链路层：停止等待", 2), _point("数据链路层：滑动窗口", 3)]
    assert len(_cluster_merge_titles(points)) == 3


def test_outline_does_not_repair_when_first_real_output_meets_contract() -> None:
    output = {"knowledge_points": [_point("CRC 差错检测", 1), _point("停止等待协议", 2)]}
    with patch("app.agents.outline.call_llm_with_meta", return_value=(output, REAL_META)) as call:
        points, meta = generate(None, 1, "数据链路层", CHUNKS, {"model": "real-model"}, return_meta=True)
    assert len(points) == 2
    assert meta["repair_attempted"] is False
    assert meta["llm_call_count"] == 1
    assert call.call_count == 1


def test_outline_uses_one_real_repair_for_structurally_weak_output() -> None:
    first = {"knowledge_points": [_point("CRC 差错检测", 1)]}
    repaired = {"knowledge_points": [_point("CRC 差错检测", 1), _point("停止等待协议", 2), _point("滑动窗口协议", 3)]}
    with patch("app.agents.outline.call_llm_with_meta", side_effect=[(first, REAL_META), (repaired, REAL_META)]) as call:
        points, meta = generate(None, 1, "数据链路层", CHUNKS, {"model": "real-model"}, return_meta=True)
    assert len(points) == 3
    assert meta["repair_attempted"] is True
    assert meta["repair_success"] is True
    assert meta["llm_call_count"] == 2
    assert call.call_count == 2


def test_outline_rejects_repair_that_falls_back() -> None:
    first = {"knowledge_points": [_point("CRC 差错检测", 1)]}
    fallback = {**REAL_META, "actual_provider": "mock", "actual_model": "mock", "fallback_used": True, "degraded": True}
    with patch("app.agents.outline.call_llm_with_meta", side_effect=[(first, REAL_META), ({"knowledge_points": [_point("停止等待协议", 2)]}, fallback)]):
        with pytest.raises(OutlineContractError, match="OUTLINE_REPAIR_REAL_META_REQUIRED"):
            generate(None, 1, "数据链路层", CHUNKS, {"model": "real-model"}, return_meta=True)
