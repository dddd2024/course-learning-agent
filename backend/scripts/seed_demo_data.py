"""Seed the database with demo data for first-run exploration.

Run from the ``backend`` directory so that ``app`` is importable::

    python scripts/seed_demo_data.py

The script is idempotent: re-running it skips records that already exist
(matched by natural keys) rather than creating duplicates. Tables are
created on demand via ``Base.metadata.create_all`` so the script can be
run right after a fresh checkout without first calling ``init_db``.

Demo content created:

* User ``demo`` / ``demo123456``.
* Two courses: 操作系统 (#409EFF) and 数据结构 (#67C23A).
* One ready ``Material`` per course with ``MaterialChunk`` produced by
  the project's own :func:`chunker.chunk_text`.
* Three ``KnowledgePoint`` rows for the 操作系统 course
  (进程调度 / 页面置换 / 死锁) with varying ``importance``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple


def _ensure_backend_on_path() -> None:
    """Make the ``app`` package importable regardless of the CWD.

    The script lives in ``backend/scripts`` and the app package in
    ``backend``, so we add ``backend`` to ``sys.path``.
    """
    here = Path(__file__).resolve()
    backend_dir = here.parent.parent
    if backend_dir.is_dir() and str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


_ensure_backend_on_path()

from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Course,
    KnowledgePoint,
    Material,
    MaterialChunk,
    User,
)
from app.retrieval.chunker import chunk_text, clean_keyword_text  # noqa: E402


DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo123456"

OS_COURSE_NAME = "操作系统"
DS_COURSE_NAME = "数据结构"

OS_MATERIAL_FILENAME = "操作系统讲义.txt"
DS_MATERIAL_FILENAME = "数据结构讲义.txt"

OS_TEXT = """\
第一章 进程管理

进程是操作系统中最基本的概念之一。进程是程序在数据集合上的一次执行过程，是系统进行资源分配和调度的基本单位。进程具有动态性、并发性、独立性和异步性等特征。

进程的三种基本状态包括就绪态、运行态和阻塞态。就绪态表示进程已具备运行条件，等待CPU分配；运行态表示进程正在CPU上执行；阻塞态表示进程因等待某事件而暂停执行。

进程控制块（PCB）是操作系统用于管理进程的核心数据结构，其中保存了进程标识、状态、寄存器、调度信息等内容。死锁是多个进程因竞争资源而互相等待的僵局，其产生有四个必要条件：互斥、占有并等待、不剥夺和循环等待。

第二章 内存管理

内存管理负责为多道程序并发执行提供支撑，主要功能包括内存分配、内存回收、地址变换和内存保护。常见的内存管理方式有连续分配、分页、分段和段页式管理。

分页存储管理将物理内存划分为固定大小的页框，将逻辑内存划分为相同大小的页，通过页表实现逻辑地址到物理地址的映射。页面置换算法在内存没有空闲页框时选择被换出的页面，常见算法有FIFO、LRU和OPT。

虚拟内存技术通过请求调入功能，将部分页面装入内存即可运行，运行时按需调入所需页面，从而实现内存的逻辑扩充。

第三章 文件系统

文件系统是操作系统用于组织、存储和管理文件资源的机制。文件是具有名字的一组相关信息的集合，文件系统负责文件的创建、删除、读写和组织。

文件的逻辑结构分为有结构文件（记录式）和无结构文件（流式）。文件的物理结构有连续分配、链接分配和索引分配等方式。

目录是文件系统用于管理文件的数据结构，常见的目录结构有单级目录、两级目录和树形目录。
"""

DS_TEXT = """\
第一章 线性表

线性表是最基本、最简单的一种数据结构，是由n（n≥0）个数据元素组成的有限序列。线性表的特点是每个元素最多有一个直接前驱和一个直接后继。

线性表有两种基本的存储结构：顺序存储结构和链式存储结构。顺序表用一组地址连续的存储单元依次存储线性表中的数据元素，便于随机访问；链表用一组任意的存储单元存储线性表中的元素，便于插入和删除操作。

第二章 树

树是一种非线性的数据结构，由n（n≥0）个节点组成的有限集合。树中有一个特定的节点称为根，其余节点分为m（m≥0）个互不相交的有限集合，每个集合本身又是一棵树。

二叉树是每个节点最多有两棵子树的树结构。二叉树的遍历方式有前序遍历、中序遍历和后序遍历。二叉搜索树支持高效的查找、插入和删除操作。

第三章 图

图是一种比树更复杂的非线性数据结构，由顶点的有穷非空集合和顶点之间的边的集合组成。图可以分为有向图和无向图。

图的存储结构有邻接矩阵和邻接表两种常用方式。图的遍历有深度优先搜索（DFS）和广度优先搜索（BFS）两种方式。最短路径算法有Dijkstra算法和Floyd算法。

第四章 排序

排序是将一组数据按照某种规则重新排列的过程，是计算机程序设计中的一种重要操作。常见的排序算法包括冒泡排序、选择排序、插入排序、快速排序、归并排序和堆排序等。

快速排序采用分治策略，平均时间复杂度为O(n log n)，是目前应用最广泛的排序算法之一。归并排序是稳定的排序算法，时间复杂度为O(n log n)。
"""


def _get_or_create_user(db: Session) -> Tuple[User, bool]:
    """Return ``(user, created)`` for the demo account."""
    user = db.query(User).filter(User.username == DEMO_USERNAME).first()
    if user is not None:
        return user, False
    user = User(
        username=DEMO_USERNAME,
        password_hash=hash_password(DEMO_PASSWORD),
        email="demo@example.com",
    )
    db.add(user)
    db.flush()
    return user, True


def _get_or_create_course(
    db: Session,
    user_id: int,
    name: str,
    teacher: str,
    semester: str,
    color: str,
) -> Tuple[Course, bool]:
    """Return ``(course, created)`` for a course owned by ``user_id``."""
    course = (
        db.query(Course)
        .filter(Course.user_id == user_id, Course.name == name)
        .first()
    )
    if course is not None:
        return course, False
    course = Course(
        user_id=user_id,
        name=name,
        teacher=teacher,
        semester=semester,
        color=color,
        description=f"{name}示范课程（演示数据）",
    )
    db.add(course)
    db.flush()
    return course, True


def _create_material_with_chunks(
    db: Session,
    user_id: int,
    course_id: int,
    filename: str,
    content: str,
) -> Tuple[Material, int]:
    """Create a ready ``Material`` plus its ``MaterialChunk``.

    If the material already exists (same course + filename), nothing is
    created and the existing chunk count is returned as the second value
    with a created-count of ``0``.
    """
    existing = (
        db.query(Material)
        .filter(
            Material.course_id == course_id,
            Material.filename == filename,
        )
        .first()
    )
    if existing is not None:
        existing_chunks = (
            db.query(MaterialChunk)
            .filter(MaterialChunk.material_id == existing.id)
            .count()
        )
        return existing, 0

    material = Material(
        user_id=user_id,
        course_id=course_id,
        filename=filename,
        file_type="txt",
        file_path=f"seed/{filename}",
        status="ready",
        version=1,
    )
    db.add(material)
    db.flush()

    created = 0
    for chunk in chunk_text(content):
        db.add(
            MaterialChunk(
                material_id=material.id,
                course_id=course_id,
                chunk_index=chunk["chunk_index"],
                title=chunk["title"],
                page_no=chunk["page_no"],
                text=chunk["text"],
                token_count=len(chunk["text"]),
                keyword_text=clean_keyword_text(chunk["text"]),
                embedding_id=None,
            )
        )
        created += 1
    db.flush()
    return material, created


def _create_knowledge_points(
    db: Session,
    user_id: int,
    course_id: int,
    material: Material,
) -> int:
    """Create three knowledge points for the OS course.

    Returns the number of points newly created (existing ones are skipped).
    """
    chunks = (
        db.query(MaterialChunk)
        .filter(MaterialChunk.material_id == material.id)
        .order_by(MaterialChunk.chunk_index)
        .all()
    )
    chunk_ids_by_title = {c.title: c.id for c in chunks}

    points = [
        {
            "title": "进程调度",
            "summary": (
                "进程调度是操作系统从就绪队列中按某种策略选择进程并分配CPU的过程，"
                "常见算法包括先来先服务、短作业优先、时间片轮转和优先级调度。"
            ),
            "importance": 5,
            "chunk_title": "第一章 进程管理",
            "exam_style": "选择题、简答题；常考调度算法比较与场景分析",
            "review_action": "对比四种调度算法的吞吐量、响应时间和公平性",
        },
        {
            "title": "页面置换",
            "summary": (
                "页面置换算法在内存没有空闲页框时选择被换出的页面，常见算法有FIFO、"
                "LRU和OPT，其中LRU基于最近最久未使用原则，命中率较高。"
            ),
            "importance": 4,
            "chunk_title": "第二章 内存管理",
            "exam_style": "计算题；给定引用串计算缺页率",
            "review_action": "手算LRU与FIFO在示例引用串下的缺页次数",
        },
        {
            "title": "死锁",
            "summary": (
                "死锁是多个进程因竞争资源而互相等待的僵局，产生条件有互斥、占有并等待、"
                "不剥夺和循环等待，可通过预防、避免（银行家算法）和检测解除来处理。"
            ),
            "importance": 3,
            "chunk_title": "第一章 进程管理",
            "exam_style": "简答题、综合题；常考四个必要条件和银行家算法",
            "review_action": "梳理死锁四个必要条件并理解银行家算法流程",
        },
    ]

    created = 0
    for p in points:
        existing = (
            db.query(KnowledgePoint)
            .filter(
                KnowledgePoint.course_id == course_id,
                KnowledgePoint.title == p["title"],
            )
            .first()
        )
        if existing is not None:
            continue
        chunk_id = chunk_ids_by_title.get(p["chunk_title"])
        source_ids = [chunk_id] if chunk_id is not None else []
        db.add(
            KnowledgePoint(
                course_id=course_id,
                user_id=user_id,
                title=p["title"],
                summary=p["summary"],
                importance=p["importance"],
                source_chunk_ids=json.dumps(source_ids),
                exam_style=p["exam_style"],
                review_action=p["review_action"],
                parent_id=None,
            )
        )
        created += 1
    db.flush()
    return created


def main() -> None:
    # Ensure tables exist (idempotent) so the seed can run on a fresh DB.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        user, user_created = _get_or_create_user(db)

        os_course, os_created = _get_or_create_course(
            db,
            user_id=user.id,
            name=OS_COURSE_NAME,
            teacher="张老师",
            semester="2026春",
            color="#409EFF",
        )
        ds_course, ds_created = _get_or_create_course(
            db,
            user_id=user.id,
            name=DS_COURSE_NAME,
            teacher="李老师",
            semester="2026春",
            color="#67C23A",
        )

        os_material, os_chunks = _create_material_with_chunks(
            db,
            user_id=user.id,
            course_id=os_course.id,
            filename=OS_MATERIAL_FILENAME,
            content=OS_TEXT,
        )
        ds_material, ds_chunks = _create_material_with_chunks(
            db,
            user_id=user.id,
            course_id=ds_course.id,
            filename=DS_MATERIAL_FILENAME,
            content=DS_TEXT,
        )

        kp_created = _create_knowledge_points(
            db,
            user_id=user.id,
            course_id=os_course.id,
            material=os_material,
        )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # Summary
    print("=" * 60)
    print("演示数据初始化完成")
    print("=" * 60)
    user_state = "新建" if user_created else "已存在"
    print(f"账号: {DEMO_USERNAME} / {DEMO_PASSWORD}（{user_state}）")
    print()
    os_state = "新建" if os_created else "已存在"
    print(
        f"课程 1: {OS_COURSE_NAME}（张老师，2026春，#409EFF）{os_state}"
    )
    print(f"  资料: {OS_MATERIAL_FILENAME}（新增 {os_chunks} 个切块）")
    print(f"  知识点: 新增 {kp_created} 个（进程调度 / 页面置换 / 死锁）")
    print()
    ds_state = "新建" if ds_created else "已存在"
    print(
        f"课程 2: {DS_COURSE_NAME}（李老师，2026春，#67C23A）{ds_state}"
    )
    print(f"  资料: {DS_MATERIAL_FILENAME}（新增 {ds_chunks} 个切块）")
    print()
    print("提示: 可使用 demo 账号登录 http://localhost:5173 体验全部功能。")


if __name__ == "__main__":
    main()
