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
* One ``StudyGoal`` (7天复习操作系统) with two ``StudyTask`` rows and
  three ``Todo`` rows (today pending / today completed / yesterday
  pending) so the Plans and Todos pages have content.
* One ``Quiz`` (操作系统第一章自测) with two choice ``QuizItem`` rows.
* One ``Conversation`` (关于死锁的提问) with one user ``Message``.
* Two ``AgentRun`` rows (course_qa / outline, both success), each with
  three ``AgentStep`` rows (retrieve / generate / validate).
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
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

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import (  # noqa: E402
    AgentRun,
    AgentStep,
    Base,
    Conversation,
    Course,
    KnowledgePoint,
    Material,
    MaterialChunk,
    Message,
    Quiz,
    QuizItem,
    StudyGoal,
    StudyTask,
    Todo,
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


def _create_todos_and_plan(
    db: Session, user: User, course: Course
) -> dict:
    """Create one StudyGoal, two StudyTasks and three Todos.

    Layout: today-pending, today-completed, yesterday-pending. All
    natural-keyed (``StudyGoal.title``, ``StudyTask.title`` per goal,
    ``Todo`` by task + title + scheduled_date) so re-runs are no-ops.
    """
    goal_title = "7天复习操作系统"
    today = date.today()
    yesterday = today - timedelta(days=1)

    goal = (
        db.query(StudyGoal)
        .filter(
            StudyGoal.user_id == user.id,
            StudyGoal.title == goal_title,
        )
        .first()
    )
    goal_created = goal is None
    if goal is None:
        goal = StudyGoal(
            user_id=user.id,
            title=goal_title,
            deadline=today + timedelta(days=7),
            daily_minutes=120,
            status="active",
        )
        db.add(goal)
        db.flush()

    task_specs = [
        {
            "title": "复习进程管理与死锁",
            "task_type": "review",
            "estimate_minutes": 120,
            "priority": 5,
            "acceptance": "能讲清进程三态转换与死锁四个必要条件",
        },
        {
            "title": "练习页面置换算法计算题",
            "task_type": "practice",
            "estimate_minutes": 90,
            "priority": 4,
            "acceptance": "能手算 FIFO/LRU 在给定引用串下的缺页次数",
        },
    ]

    tasks: list[StudyTask] = []
    tasks_created = 0
    for spec in task_specs:
        task = (
            db.query(StudyTask)
            .filter(
                StudyTask.goal_id == goal.id,
                StudyTask.title == spec["title"],
            )
            .first()
        )
        if task is None:
            task = StudyTask(
                goal_id=goal.id,
                course_id=course.id,
                title=spec["title"],
                task_type=spec["task_type"],
                estimate_minutes=spec["estimate_minutes"],
                priority=spec["priority"],
                acceptance=spec["acceptance"],
                status="pending",
            )
            db.add(task)
            db.flush()
            tasks_created += 1
        tasks.append(task)

    todo_specs = [
        {
            "task": tasks[0],
            "title": "复习进程管理章节",
            "scheduled_date": today,
            "status": "pending",
            "completed_at": None,
        },
        {
            "task": tasks[0],
            "title": "整理死锁四个必要条件笔记",
            "scheduled_date": today,
            "status": "completed",
            "completed_at": datetime(
                today.year, today.month, today.day, 14, 30, 0
            ),
        },
        {
            "task": tasks[1],
            "title": "完成页面置换练习题",
            "scheduled_date": yesterday,
            "status": "pending",
            "completed_at": None,
        },
    ]

    todos_created = 0
    for spec in todo_specs:
        existing = (
            db.query(Todo)
            .filter(
                Todo.task_id == spec["task"].id,
                Todo.title == spec["title"],
                Todo.scheduled_date == spec["scheduled_date"],
            )
            .first()
        )
        if existing is not None:
            continue
        db.add(
            Todo(
                user_id=user.id,
                task_id=spec["task"].id,
                course_id=course.id,
                title=spec["title"],
                scheduled_date=spec["scheduled_date"],
                status=spec["status"],
                completed_at=spec["completed_at"],
                estimate_minutes=spec["task"].estimate_minutes,
            )
        )
        todos_created += 1
    db.flush()
    return {
        "goal_created": goal_created,
        "tasks_created": tasks_created,
        "todos_created": todos_created,
    }


def _create_quiz(db: Session, user: User, course: Course) -> dict:
    """Create one Quiz with two choice QuizItems for the OS course."""
    quiz_title = "操作系统第一章自测"
    existing = (
        db.query(Quiz)
        .filter(
            Quiz.user_id == user.id,
            Quiz.course_id == course.id,
            Quiz.title == quiz_title,
        )
        .first()
    )
    if existing is not None:
        return {"quiz_created": False, "items_created": 0}

    quiz = Quiz(
        user_id=user.id,
        course_id=course.id,
        title=quiz_title,
        question_count=2,
        status="draft",
    )
    db.add(quiz)
    db.flush()

    items = [
        {
            "question_type": "choice",
            "question_text": "产生死锁的四个必要条件中，不包含以下哪一项？",
            "options": [
                "A. 互斥",
                "B. 占有并等待",
                "C. 先来先服务",
                "D. 循环等待",
            ],
            "answer": "C",
            "explanation": (
                "死锁的四个必要条件是互斥、占有并等待、不剥夺和循环等待；"
                "先来先服务是进程调度算法，与死锁条件无关。"
            ),
            "order_index": 0,
        },
        {
            "question_type": "choice",
            "question_text": "下列页面置换算法中，可能产生 Belady 异常的是？",
            "options": ["A. LRU", "B. FIFO", "C. OPT", "D. LFU"],
            "answer": "B",
            "explanation": (
                "FIFO 在增加物理页框时可能出现缺页率上升的 Belady 异常，"
                "LRU 和 OPT 不会出现该异常。"
            ),
            "order_index": 1,
        },
    ]

    for it in items:
        db.add(
            QuizItem(
                quiz_id=quiz.id,
                question_type=it["question_type"],
                question_text=it["question_text"],
                options=json.dumps(it["options"], ensure_ascii=False),
                answer=it["answer"],
                explanation=it["explanation"],
                order_index=it["order_index"],
            )
        )
    db.flush()
    return {"quiz_created": True, "items_created": len(items)}


def _create_conversation(db: Session, user: User, course: Course) -> dict:
    """Create one Conversation with a single user Message for the OS course."""
    conv_title = "关于死锁的提问"
    existing = (
        db.query(Conversation)
        .filter(
            Conversation.user_id == user.id,
            Conversation.course_id == course.id,
            Conversation.title == conv_title,
        )
        .first()
    )
    if existing is not None:
        return {"conv_created": False, "messages_created": 0}

    conv = Conversation(
        user_id=user.id,
        course_id=course.id,
        title=conv_title,
    )
    db.add(conv)
    db.flush()

    db.add(
        Message(
            conversation_id=conv.id,
            role="user",
            content="什么是死锁？",
            answer_json=None,
        )
    )
    db.flush()
    return {"conv_created": True, "messages_created": 1}


def _create_agent_runs(db: Session, user: User, course: Course) -> dict:
    """Create two AgentRuns (course_qa / outline) with three steps each.

    Idempotency: skip a run_type once the user already has at least one
    run of that type (count-based natural key on user_id + run_type).
    """
    now = datetime.now()
    started_at = now - timedelta(minutes=10)
    finished_at = now - timedelta(minutes=9)

    run_specs = [
        {
            "run_type": "course_qa",
            "input_summary": {
                "question": "什么是死锁？",
                "course_id": course.id,
            },
            "output_summary": {
                "answer": "死锁是多个进程因竞争资源而互相等待的僵局……",
            },
            "steps": [
                {
                    "step_name": "retrieve",
                    "step_index": 0,
                    "input_data": {"query": "什么是死锁？", "top_k": 4},
                    "output_data": {
                        "chunks": ["第一章 进程管理……死锁四个必要条件……"]
                    },
                    "duration_ms": 120,
                },
                {
                    "step_name": "generate",
                    "step_index": 1,
                    "input_data": {
                        "question": "什么是死锁？",
                        "context": "死锁是多个进程……",
                    },
                    "output_data": {
                        "answer": "死锁是多个进程因竞争资源而互相等待的僵局……"
                    },
                    "duration_ms": 850,
                },
                {
                    "step_name": "validate",
                    "step_index": 2,
                    "input_data": {"answer": "死锁是……"},
                    "output_data": {"valid": True, "issues": []},
                    "duration_ms": 30,
                },
            ],
        },
        {
            "run_type": "outline",
            "input_summary": {"course_id": course.id, "material": "demo"},
            "output_summary": {"knowledge_points": 3},
            "steps": [
                {
                    "step_name": "retrieve",
                    "step_index": 0,
                    "input_data": {"material": "demo", "scope": "all"},
                    "output_data": {
                        "chunks": ["进程管理", "内存管理", "文件系统"]
                    },
                    "duration_ms": 90,
                },
                {
                    "step_name": "generate",
                    "step_index": 1,
                    "input_data": {
                        "chunks": ["进程管理", "内存管理", "文件系统"]
                    },
                    "output_data": {
                        "points": ["进程调度", "页面置换", "死锁"]
                    },
                    "duration_ms": 1200,
                },
                {
                    "step_name": "validate",
                    "step_index": 2,
                    "input_data": {
                        "points": ["进程调度", "页面置换", "死锁"]
                    },
                    "output_data": {"valid": True, "issues": []},
                    "duration_ms": 40,
                },
            ],
        },
    ]

    runs_created = 0
    steps_created = 0
    for spec in run_specs:
        existing_count = (
            db.query(AgentRun)
            .filter(
                AgentRun.user_id == user.id,
                AgentRun.run_type == spec["run_type"],
            )
            .count()
        )
        if existing_count > 0:
            continue
        run = AgentRun(
            user_id=user.id,
            run_type=spec["run_type"],
            status="success",
            input_summary=json.dumps(
                spec["input_summary"], ensure_ascii=False
            ),
            output_summary=json.dumps(
                spec["output_summary"], ensure_ascii=False
            ),
            prompt_version="v1",
            model_name="mock",
            provider="mock",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=1000,
        )
        db.add(run)
        db.flush()
        runs_created += 1
        for step in spec["steps"]:
            db.add(
                AgentStep(
                    run_id=run.id,
                    step_name=step["step_name"],
                    step_index=step["step_index"],
                    input_data=json.dumps(
                        step["input_data"], ensure_ascii=False
                    ),
                    output_data=json.dumps(
                        step["output_data"], ensure_ascii=False
                    ),
                    duration_ms=step["duration_ms"],
                    status="success",
                )
            )
            steps_created += 1
    db.flush()
    return {"runs_created": runs_created, "steps_created": steps_created}


def _ensure_agent_runs_schema() -> None:
    """Back-fill missing columns on a legacy ``agent_runs`` table.

    ``Base.metadata.create_all`` only creates missing tables — it does
    not add new columns to existing ones. Older databases created the
    ``agent_runs`` table before the ``provider`` / ``config_id`` columns
    were introduced, so we ALTER them in here to keep the seed runnable
    on a legacy DB without wiping data.
    """
    inspector = inspect(engine)
    if "agent_runs" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("agent_runs")}
    with engine.begin() as conn:
        if "provider" not in existing:
            conn.execute(text("ALTER TABLE agent_runs ADD COLUMN provider VARCHAR(50)"))
        if "config_id" not in existing:
            conn.execute(text("ALTER TABLE agent_runs ADD COLUMN config_id INTEGER"))


def main() -> None:
    # Ensure tables exist (idempotent) so the seed can run on a fresh DB.
    Base.metadata.create_all(bind=engine)
    # Back-fill any missing columns on legacy tables (no-op on fresh DBs).
    _ensure_agent_runs_schema()

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

        plan_result = _create_todos_and_plan(db, user, os_course)
        quiz_result = _create_quiz(db, user, os_course)
        conv_result = _create_conversation(db, user, os_course)
        runs_result = _create_agent_runs(db, user, os_course)

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
    plan_state = "新建" if plan_result["goal_created"] else "已存在"
    print(f"学习目标: 7天复习操作系统（{plan_state}，daily 120 分钟）")
    print(
        f"  任务: 新增 {plan_result['tasks_created']} 个"
        f"（复习进程管理与死锁 / 练习页面置换算法计算题）"
    )
    print(
        f"  待办: 新增 {plan_result['todos_created']} 个"
        f"（今日待办 / 今日已完成 / 昨日待办）"
    )
    print()
    quiz_state = "新建" if quiz_result["quiz_created"] else "已存在"
    print(
        f"测验: 操作系统第一章自测（{quiz_state}，"
        f"新增 {quiz_result['items_created']} 道选择题）"
    )
    print()
    conv_state = "新建" if conv_result["conv_created"] else "已存在"
    print(
        f"对话: 关于死锁的提问（{conv_state}，"
        f"新增 {conv_result['messages_created']} 条用户消息）"
    )
    print()
    runs_state = "新建" if runs_result["runs_created"] else "已存在"
    print(
        f"Agent 运行: {runs_state}，"
        f"新增 {runs_result['runs_created']} 条 run / "
        f"{runs_result['steps_created']} 条 step"
        f"（course_qa + outline，各 3 步：retrieve/generate/validate）"
    )
    print()
    print("提示: 可使用 demo 账号登录 http://localhost:5173 体验全部功能。")


if __name__ == "__main__":
    main()
