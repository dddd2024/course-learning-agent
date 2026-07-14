from __future__ import annotations

from app.agents.outline import _repair_results, evaluate_outline_contract


MATH_CHUNKS = [
    {"chunk_id": 123, "text": "导数描述函数在一点附近的变化率。"},
    {"chunk_id": 456, "text": "定积分可以表示曲边图形的面积。"},
]
DATABASE_CHUNKS = [
    {"chunk_id": 91, "text": "第三范式要求非主属性不传递依赖于主键。"},
    {"chunk_id": 92, "text": "事务具有原子性、一致性、隔离性和持久性。"},
]


def _point(title: str, chunk_id: object, quote: str) -> dict:
    return {
        "title": title,
        "summary": title,
        "importance": 3,
        "source_chunk_ids": [chunk_id],
        "source_evidence": [{"chunk_id": chunk_id, "quote_text": quote}],
        "exam_style": "解释",
        "review_action": "复习",
    }


def test_math_repair_keeps_two_distinct_verbatim_points() -> None:
    points, unsupported = _repair_results([
        _point("导数定义", 123, "导数描述函数在一点附近的变化率。"),
        _point("定积分", 456, "定积分可以表示曲边图形的面积。"),
    ], MATH_CHUNKS)

    assert unsupported == 0
    assert evaluate_outline_contract(points, MATH_CHUNKS)["passed"] is True


def test_database_repair_keeps_two_distinct_verbatim_points() -> None:
    points, unsupported = _repair_results([
        _point("第三范式", 91, "第三范式要求非主属性不传递依赖于主键。"),
        _point("事务特性", 92, "事务具有原子性、一致性、隔离性和持久性。"),
    ], DATABASE_CHUNKS)

    assert unsupported == 0
    assert evaluate_outline_contract(points, DATABASE_CHUNKS)["passed"] is True


def test_cross_course_title_with_legal_math_quote_is_rejected() -> None:
    points, unsupported = _repair_results([
        _point("滑动窗口协议", 123, "导数描述函数在一点附近的变化率。"),
    ], MATH_CHUNKS)

    assert points == []
    assert unsupported == 1


def test_fabricated_quote_is_rejected() -> None:
    points, unsupported = _repair_results([
        _point("导数定义", 123, "导数是无限小的比值。"),
    ], MATH_CHUNKS)

    assert points == []
    assert unsupported == 1


def test_string_chunk_ids_are_reconciled_exactly() -> None:
    points, unsupported = _repair_results([
        _point("导数定义", "chunk_id=123", "导数描述函数在一点附近的变化率。"),
        _point("定积分", "456", "定积分可以表示曲边图形的面积。"),
    ], MATH_CHUNKS)

    assert unsupported == 0
    assert [point["source_chunk_ids"] for point in points] == [[123], [456]]


def test_duplicate_titles_remain_contract_failures() -> None:
    contract = evaluate_outline_contract([
        _point("导数定义", 123, "导数描述函数在一点附近的变化率。"),
        _point("导数定义", 456, "定积分可以表示曲边图形的面积。"),
    ], MATH_CHUNKS)

    assert contract["duplicate_title_count"] == 1
    assert contract["passed"] is False
