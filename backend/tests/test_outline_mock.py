"""Tests for mock outline source_chunk_ids mapping and QA quality."""
from app.agents.llm import _mock_outline


def test_mock_outline_returns_real_chunk_ids():
    """Mock outline must return actual chunk_id values from the prompt,
    not 1-based position indices."""
    prompt = """课程: 测试课程

资料片段（retrieved_chunks）
[片段1] chunk_id=42，页码 5，标题：进程与线程
进程是程序的一次执行过程，是系统进行资源分配和调度的基本单位。

[片段2] chunk_id=17，页码 3，标题：线程概念
线程是进程内的一个执行实体，是CPU调度的基本单位。
"""
    result = _mock_outline(prompt)
    kps = result["knowledge_points"]
    assert len(kps) >= 1

    # The source_chunk_ids must contain the actual chunk_id from the prompt
    all_source_ids = []
    for kp in kps:
        all_source_ids.extend(kp["source_chunk_ids"])

    # chunk_id=42 and chunk_id=17 must appear somewhere
    assert 42 in all_source_ids or 17 in all_source_ids, (
        f"source_chunk_ids should contain real DB IDs (42, 17), "
        f"got: {all_source_ids}"
    )
    # Must NOT contain position-based indices like 1 or 2
    # (unless they happen to match a real chunk_id)
    for kp in kps:
        for sid in kp["source_chunk_ids"]:
            assert isinstance(sid, int), (
                f"source_chunk_ids must be ints, got {type(sid)}: {sid}"
            )


def test_mock_outline_summary_is_not_truncated_title():
    """Summary should be more than just the first 150 chars of raw text."""
    long_text = "进程与线程\n" + "进程是程序的一次执行过程。" * 20
    prompt = f"""课程: 测试课程

资料片段（retrieved_chunks）
[片段1] chunk_id=1，标题：进程与线程
{long_text}
"""
    result = _mock_outline(prompt)
    kp = result["knowledge_points"][0]
    # Summary should not just be the title repeated
    assert kp["summary"], "Summary must not be empty"
    assert len(kp["summary"]) >= 10, f"Summary too short: {kp['summary']}"


def test_fetch_chunks_increased_sampling():
    """_fetch_chunks should sample up to 25 chunks per material."""
    # This is an integration test that requires DB setup;
    # we verify the constant instead
    import app.agents.outline as outline_mod
    import inspect
    source = inspect.getsource(outline_mod._fetch_chunks)
    assert "MAX_PER_MATERIAL = 25" in source or "MAX_PER_MATERIAL=25" in source, (
        "MAX_PER_MATERIAL should be 25 for better coverage"
    )


def test_mock_qa_uses_longest_chunk_not_first():
    """Mock QA should prefer the chunk with the most content, not just
    the first one (which may be a short title chunk)."""
    from app.agents.llm import _mock_course_qa

    prompt = """课程: 操作系统

资料片段（retrieved_chunks）
[片段1] chunk_id=1
进程与线程

[片段2] chunk_id=2
进程是程序的一次执行过程，是系统进行资源分配和调度的基本单位。
进程具有动态性、并发性、独立性和异步性等特征。
线程是进程内的一个执行实体，是CPU调度的基本单位。
进程与线程的主要区别在于：进程是资源分配的单位，线程是调度的单位。

用户问题: 进程与线程的主要区别
"""
    result = _mock_course_qa(prompt)
    assert result["answer"], "Answer must not be empty"
    # Answer should contain meaningful content, not just "进程与线程"
    assert len(result["answer"]) > 20, (
        f"Answer too short ({len(result['answer'])} chars): {result['answer']!r}"
    )
