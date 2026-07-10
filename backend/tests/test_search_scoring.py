# backend/tests/test_search_scoring.py
"""Tests for search scoring fairness between title and body chunks.

The old density-based scoring (raw_score / (text_len / 100)) inflated
scores for short title-only chunks: a 5-char title with 2 keyword hits
produced density=60 (capped to 1.0), while a 120-char body chunk with 10
hits produced density=8.3 (score ~0.2). This meant title-only chunks
crowded out chunks with actual explanatory content.

The new scoring uses absolute hit count + coverage + length bonus, with
a penalty/filter for title-only chunks that lack real body text.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.course import Course
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.user import User
from app.retrieval.search import keyword_search


@pytest.fixture()
def db_session():
    """In-memory SQLite session for scoring tests.

    Creates all tables fresh, yields a session, then drops everything.
    This mirrors the pattern in app/tests/conftest.py but is self-
    contained so the test does not depend on external fixtures.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _setup_course_with_material(db_session):
    """Create a user, course, and ready material, return (course, material)."""
    user = User(
        username="scoring_tester",
        password_hash="x",
        email="scorer@test.com",
    )
    db_session.add(user)
    db_session.commit()

    course = Course(name="操作系统", user_id=user.id)
    db_session.add(course)
    db_session.commit()

    mat = Material(
        course_id=course.id,
        filename="test.pdf",
        file_type="pdf",
        file_path="test.pdf",
        status="ready",
        user_id=user.id,
    )
    db_session.add(mat)
    db_session.commit()
    return course, mat


def test_body_chunk_scores_higher_than_title_only(db_session):
    """A chunk with detailed body text should score higher than a
    title-only chunk for a conceptual query.

    Before the fix, the title-only chunk (5 chars, 2 hits) got
    density=120 -> score 1.0, while the body chunk (120 chars, 10 hits)
    got density=8.3 -> score ~0.22. After the fix, the body chunk
    should win (or the title-only chunk should be filtered out).
    """
    course, mat = _setup_course_with_material(db_session)

    # Title-only chunk (short, high density under old scoring)
    title_chunk = MaterialChunk(
        material_id=mat.id,
        course_id=course.id,
        chunk_index=0,
        title="进程与线程",
        text="进程与线程",
        token_count=5,
        keyword_text="进程与线程",
    )
    # Body chunk with detailed content (longer, lower density but more info)
    body_text = (
        "进程与线程的主要区别在于：进程是资源分配的基本单位，"
        "线程是CPU调度的基本单位。进程拥有独立的地址空间，"
        "线程共享进程的地址空间。进程间通信需要IPC机制，"
        "线程间通信可以直接访问共享变量。"
        "进程创建开销大，线程创建开销小。"
    )
    body_chunk = MaterialChunk(
        material_id=mat.id,
        course_id=course.id,
        chunk_index=1,
        title="进程与线程的主要区别",
        text=body_text,
        token_count=120,
        keyword_text="进程与线程的主要区别在于 资源分配 CPU调度 地址空间",
    )
    db_session.add_all([title_chunk, body_chunk])
    db_session.commit()

    results = keyword_search(
        db_session, course.id, "进程与线程的主要区别"
    )

    body_result = next(
        (r for r in results if r["chunk_id"] == body_chunk.id), None
    )
    title_result = next(
        (r for r in results if r["chunk_id"] == title_chunk.id), None
    )

    # Body chunk must appear in results
    assert body_result is not None, (
        "Body chunk should be in search results"
    )

    # Body chunk should score >= title chunk (or title chunk filtered out)
    if title_result is not None:
        assert body_result["score"] >= title_result["score"], (
            f"Body chunk score ({body_result['score']}) should be >= "
            f"title chunk score ({title_result['score']})"
        )


def test_title_only_chunk_filtered_or_penalized(db_session):
    """A chunk whose text is just the title (no body content) should
    either be filtered out or score significantly lower than a chunk
    with real body text."""
    course, mat = _setup_course_with_material(db_session)

    # Pure title chunk — text IS the title, no body content
    pure_title = MaterialChunk(
        material_id=mat.id,
        course_id=course.id,
        chunk_index=0,
        title="虚拟内存管理",
        text="虚拟内存管理",
        token_count=5,
        keyword_text="虚拟内存管理",
    )
    # Chunk with real body content
    body_text = (
        "虚拟内存管理是操作系统的重要功能之一。"
        "虚拟内存通过页表机制将虚拟地址映射到物理地址，"
        "使得每个进程拥有独立的地址空间。"
        "当物理内存不足时，操作系统可以将不常用的页面换出到磁盘，"
        "从而实现内存的过度分配。"
    )
    body = MaterialChunk(
        material_id=mat.id,
        course_id=course.id,
        chunk_index=1,
        title="虚拟内存管理",
        text=body_text,
        token_count=100,
        keyword_text="虚拟内存管理 操作系统 页表 地址空间",
    )
    db_session.add_all([pure_title, body])
    db_session.commit()

    results = keyword_search(db_session, course.id, "虚拟内存管理")

    body_result = next(
        (r for r in results if r["chunk_id"] == body.id), None
    )
    title_result = next(
        (r for r in results if r["chunk_id"] == pure_title.id), None
    )

    assert body_result is not None, "Body chunk should be in results"

    # Title-only chunk should either be absent or score strictly lower
    if title_result is not None:
        assert body_result["score"] > title_result["score"], (
            f"Body chunk ({body_result['score']}) should strictly "
            f"outscore title-only chunk ({title_result['score']})"
        )


def test_long_body_chunk_not_filtered_by_density(db_session):
    """A long body chunk with a few keyword hits should NOT be filtered
    out. Under the old density < 0.5 filter, a 600-char chunk with 3
    hits had density=0.5 and was borderline-removed."""
    course, mat = _setup_course_with_material(db_session)

    # 600+ char body with only 3 mentions of the keyword
    body_text = (
        "进程是程序的一次执行过程，是系统进行资源分配和调度的基本单位。"
        "进程具有动态性、并发性、独立性和异步性等特征。"
        "进程的基本状态包括就绪、运行和阻塞三种状态。"
        "进程控制块(PCB)是操作系统用于管理进程的核心数据结构，"
        "其中包含了进程标识符、状态、寄存器、调度信息等。"
        "进程的创建需要分配PCB、分配资源、初始化地址空间等步骤。"
        "进程的终止需要回收资源、撤销PCB等操作。"
        "进程间通信(IPC)是操作系统中进程交换信息的重要机制。"
        "常见的IPC方式包括管道、消息队列、共享内存和信号量等。"
        "进程调度是操作系统的核心功能之一，决定了哪个进程获得CPU。"
    )
    chunk = MaterialChunk(
        material_id=mat.id,
        course_id=course.id,
        chunk_index=0,
        title="进程管理",
        text=body_text,
        token_count=200,
        keyword_text="进程管理 操作系统 PCB 调度",
    )
    db_session.add(chunk)
    db_session.commit()

    results = keyword_search(db_session, course.id, "进程管理")

    result = next(
        (r for r in results if r["chunk_id"] == chunk.id), None
    )
    assert result is not None, (
        "Long body chunk with keyword hits should not be filtered out"
    )
    assert result["score"] > 0
