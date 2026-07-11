# backend/tests/test_chunker_merge.py
"""Tests for chunker title-body merging."""
from app.retrieval.chunker import chunk_text


def test_consecutive_headings_are_merged():
    """Two consecutive heading lines should not produce a title-only chunk."""
    text = """3.1 进程与线程
3.1.1 进程概念
进程是程序的一次执行过程，是系统进行资源分配和调度的基本单位。
进程具有动态性、并发性、独立性和异步性等特征。
"""
    chunks = chunk_text(text)
    # No chunk should have text == title (pure title chunk)
    for chunk in chunks:
        if chunk["title"]:
            text_stripped = chunk["text"].strip()
            title_stripped = chunk["title"].strip()
            assert text_stripped != title_stripped, (
                f"Pure title chunk found: title={title_stripped!r}, "
                f"text={text_stripped!r}"
            )


def test_single_heading_followed_by_body():
    """A heading followed by body text should produce one chunk."""
    text = """2.1 线程的概念
线程是进程内的一个执行实体。
线程是CPU调度的基本单位。
"""
    chunks = chunk_text(text)
    assert len(chunks) >= 1
    assert chunks[0]["title"] is not None
    assert "线程" in chunks[0]["text"]
