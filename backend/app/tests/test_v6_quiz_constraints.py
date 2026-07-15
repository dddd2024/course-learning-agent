"""V6-31 and V6-32 tests: quiz input constraints and weak point change explanations.

V6-31: Strictly enforce quiz input constraints.
  - question_count must be honoured (exact, truncate excess, retry on fewer)
  - Question types restricted to the allowed set
  - Every item must have source_evidence (chunk_id + quote_text)
  - Every item must have a valid knowledge_point_id

V6-32: Weak point updates with explainable changes.
  - _upsert_weak_point returns a change summary describing what changed
  - change summary includes previous/current values for all tracked fields
  - QuizResultOut includes weak_point_changes

TDD: tests written first, expected to fail until implementation.
"""
import json

import pytest

from app.agents.quiz import generate_quiz
from app.api.v1.endpoints.quizzes import _upsert_weak_point
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.material_chunk import MaterialChunk
from app.models.quiz import WeakPoint
from app.models.user import User

CHUNK_TEXTS = [
    "快表TLB是页表的高速缓存用于加速地址转换",
    "页表存储虚拟页到物理页的映射关系",
    "虚拟内存管理通过分页机制实现页面隔离",
    "缺页中断由操作系统处理并调入所需页面",
    "页面置换算法决定哪些页面被换出内存",
    "进程调度策略决定CPU分配给哪个进程",
    "文件系统管理磁盘上的数据存储和检索",
]


# ===================================================================
# Helpers
# ===================================================================

def _setup_env(db_session, n_chunks=5, n_kps=5):
    """Set up user, course, material chunks, and knowledge points."""
    user = User(username="testuser", email="test@test.com", password_hash="x")
    db_session.add(user)
    db_session.flush()

    course = Course(name="操作系统", user_id=user.id)
    db_session.add(course)
    db_session.flush()

    chunks = []
    for i in range(min(n_chunks, len(CHUNK_TEXTS))):
        chunk = MaterialChunk(
            material_id=1,
            course_id=course.id,
            chunk_index=i,
            text=CHUNK_TEXTS[i],
            is_active=1,
            page_no=i + 1,
        )
        db_session.add(chunk)
        chunks.append(chunk)
    db_session.flush()

    kps = []
    for i in range(n_kps):
        chunk_id = chunks[i % len(chunks)].id
        kp = KnowledgePoint(
            course_id=course.id,
            user_id=user.id,
            title=f"知识点{i + 1}",
            summary=f"摘要{i + 1}",
            source_chunk_ids=json.dumps([chunk_id]),
            status="active",
        )
        db_session.add(kp)
        kps.append(kp)
    db_session.flush()

    return user, course, chunks, kps


def _make_tf_question(idx, chunk, **overrides):
    """Build a valid true_false question that passes all checks."""
    text = chunk.text
    q = {
        "question_type": "true_false",
        "difficulty": 3,
        "stem": f"根据课程资料，{text}",
        "options": [],
        "answer": "true",
        "explanation": "该说法直接来自课程资料原文。",
        "rubric": [],
        "knowledge_point_ids": [f"kp_{idx + 1}"],
        "source_chunk_ids": [str(chunk.id)],
        "source_evidence": [
            {"chunk_id": chunk.id, "quote_text": text},
        ],
    }
    q.update(overrides)
    return q


def _mock_meta():
    return {
        "provider": "mock",
        "model_name": "mock",
        "fallback_used": False,
        "fallback_reason": None,
        "fallback_chain": [{"provider": "mock", "status": "success"}],
        "degraded": False,
    }


# ===================================================================
# V6-31: Quiz Input Constraints
# ===================================================================

def test_quiz_respects_question_count(db_session, monkeypatch):
    """Request 5 questions, get exactly 5."""
    user, course, chunks, kps = _setup_env(db_session, n_chunks=5, n_kps=5)

    questions = [_make_tf_question(i, chunks[i]) for i in range(5)]

    def mock_llm(prompt, agent_type, schema=None, user_config=None):
        return ({"questions": questions}, _mock_meta())

    monkeypatch.setattr("app.agents.quiz.call_llm_with_meta", mock_llm)

    result = generate_quiz(
        db=db_session,
        user_id=user.id,
        course_id=course.id,
        knowledge_points=kps,
        course_name="操作系统",
        question_count=5,
    )

    assert len(result["items"]) == 5
    assert result["generated_count"] == 5
    assert result["requested_count"] == 5
    assert result["partial_generation"] is False


def test_quiz_truncates_excess_questions(db_session, monkeypatch):
    """If LLM returns 7, keep only 5."""
    user, course, chunks, kps = _setup_env(db_session, n_chunks=7, n_kps=7)

    questions = [_make_tf_question(i, chunks[i]) for i in range(7)]

    def mock_llm(prompt, agent_type, schema=None, user_config=None):
        return ({"questions": questions}, _mock_meta())

    monkeypatch.setattr("app.agents.quiz.call_llm_with_meta", mock_llm)

    result = generate_quiz(
        db=db_session,
        user_id=user.id,
        course_id=course.id,
        knowledge_points=kps,
        course_name="操作系统",
        question_count=5,
    )

    assert len(result["items"]) == 5
    assert result["generated_count"] == 5
    assert result["requested_count"] == 5


def test_quiz_drops_items_without_evidence(db_session, monkeypatch):
    """Items without source_evidence are dropped."""
    user, course, chunks, kps = _setup_env(db_session, n_chunks=5, n_kps=5)

    # Question 0: has source_chunk_ids but no source_evidence list
    q_no_evidence = _make_tf_question(0, chunks[0])
    q_no_evidence["source_evidence"] = []

    # Questions 1-4: valid
    questions = [q_no_evidence] + [
        _make_tf_question(i, chunks[i]) for i in range(1, 5)
    ]

    def mock_llm(prompt, agent_type, schema=None, user_config=None):
        return ({"questions": questions}, _mock_meta())

    monkeypatch.setattr("app.agents.quiz.call_llm_with_meta", mock_llm)

    result = generate_quiz(
        db=db_session,
        user_id=user.id,
        course_id=course.id,
        knowledge_points=kps,
        course_name="操作系统",
        question_count=5,
    )

    # The item without evidence should be dropped
    assert len(result["items"]) == 4
    for item in result["items"]:
        assert len(item["source_evidence"]) > 0


def test_generate_quiz_performs_exactly_one_provider_call(db_session, monkeypatch):
    """Deficit retries belong to QuizCreationService, never the agent."""
    user, course, chunks, kps = _setup_env(db_session, n_chunks=1, n_kps=1)
    invalid = _make_tf_question(0, chunks[0], source_evidence=[])
    calls = []

    def mock_llm(prompt, agent_type, schema=None, user_config=None):
        calls.append((prompt, agent_type))
        return {"questions": [invalid]}, _mock_meta()

    monkeypatch.setattr("app.agents.quiz.call_llm_with_meta", mock_llm)

    result = generate_quiz(
        db=db_session,
        user_id=user.id,
        course_id=course.id,
        knowledge_points=kps,
        course_name="操作系统",
        question_count=1,
    )

    assert result["generated_count"] == 0
    assert len(calls) == 1


def test_quiz_drops_items_with_invalid_kp(db_session, monkeypatch):
    """Items with invalid KP references are dropped."""
    user, course, chunks, kps = _setup_env(db_session, n_chunks=5, n_kps=5)

    # Question 0: invalid KP reference (kp_999 doesn't exist)
    q_invalid_kp = _make_tf_question(0, chunks[0])
    q_invalid_kp["knowledge_point_ids"] = ["kp_999"]

    # Questions 1-4: valid
    questions = [q_invalid_kp] + [
        _make_tf_question(i, chunks[i]) for i in range(1, 5)
    ]

    def mock_llm(prompt, agent_type, schema=None, user_config=None):
        return ({"questions": questions}, _mock_meta())

    monkeypatch.setattr("app.agents.quiz.call_llm_with_meta", mock_llm)

    result = generate_quiz(
        db=db_session,
        user_id=user.id,
        course_id=course.id,
        knowledge_points=kps,
        course_name="操作系统",
        question_count=5,
    )

    # The item with invalid KP should be dropped
    assert len(result["items"]) == 4
    for item in result["items"]:
        assert item["knowledge_point_id"] is not None


def test_quiz_partial_generation_when_fewer_questions(db_session, monkeypatch):
    """If LLM returns 3 when 5 requested, note partial_generation."""
    user, course, chunks, kps = _setup_env(db_session, n_chunks=5, n_kps=5)

    questions = [_make_tf_question(i, chunks[i]) for i in range(3)]

    def mock_llm(prompt, agent_type, schema=None, user_config=None):
        return ({"questions": questions}, _mock_meta())

    monkeypatch.setattr("app.agents.quiz.call_llm_with_meta", mock_llm)

    result = generate_quiz(
        db=db_session,
        user_id=user.id,
        course_id=course.id,
        knowledge_points=kps,
        course_name="操作系统",
        question_count=5,
    )

    assert result["generated_count"] == 3
    assert result["requested_count"] == 5
    assert result["partial_generation"] is True
    assert result["generated_count"] < result["requested_count"]


def test_quiz_question_types_validated(db_session, monkeypatch):
    """Invalid question types are rejected."""
    user, course, chunks, kps = _setup_env(db_session, n_chunks=5, n_kps=5)

    # Question 0: invalid type
    q_invalid_type = _make_tf_question(0, chunks[0])
    q_invalid_type["question_type"] = "essay"

    # Questions 1-4: valid
    questions = [q_invalid_type] + [
        _make_tf_question(i, chunks[i]) for i in range(1, 5)
    ]

    def mock_llm(prompt, agent_type, schema=None, user_config=None):
        return ({"questions": questions}, _mock_meta())

    monkeypatch.setattr("app.agents.quiz.call_llm_with_meta", mock_llm)

    result = generate_quiz(
        db=db_session,
        user_id=user.id,
        course_id=course.id,
        knowledge_points=kps,
        course_name="操作系统",
        question_count=5,
    )

    # The invalid type item should be dropped
    assert len(result["items"]) == 4
    valid_types = {"choice", "multiple_choice", "true_false", "short_answer"}
    for item in result["items"]:
        assert item["question_type"] in valid_types


def test_quiz_all_items_have_evidence(db_session, monkeypatch):
    """Every surviving item has non-empty source_evidence."""
    user, course, chunks, kps = _setup_env(db_session, n_chunks=5, n_kps=5)

    questions = [_make_tf_question(i, chunks[i]) for i in range(5)]

    def mock_llm(prompt, agent_type, schema=None, user_config=None):
        return ({"questions": questions}, _mock_meta())

    monkeypatch.setattr("app.agents.quiz.call_llm_with_meta", mock_llm)

    result = generate_quiz(
        db=db_session,
        user_id=user.id,
        course_id=course.id,
        knowledge_points=kps,
        course_name="操作系统",
        question_count=5,
    )

    assert len(result["items"]) > 0
    for item in result["items"]:
        evidence = item.get("source_evidence", [])
        assert isinstance(evidence, list)
        assert len(evidence) > 0
        for ev in evidence:
            assert ev.get("chunk_id") is not None
            assert ev.get("quote_text")  # non-empty


# ===================================================================
# V6-32: Weak Point Change Explanations
# ===================================================================

def test_weak_point_creation_explained(db_session, sample_user, sample_course):
    """First wrong answer creates weak point with change summary."""
    kp = KnowledgePoint(
        course_id=sample_course.id,
        user_id=sample_user.id,
        title="测试知识点",
        source_chunk_ids="[]",
        status="active",
    )
    db_session.add(kp)
    db_session.flush()

    change = _upsert_weak_point(
        db_session,
        user_id=sample_user.id,
        course_id=sample_course.id,
        knowledge_point_id=kp.id,
        correct=False,
    )

    assert change is not None
    assert change["action"] == "created"
    assert change["correct"] is False
    assert change["knowledge_point_id"] == kp.id

    # Check previous and current values
    assert change["previous"]["wrong_count"] == 0
    assert change["current"]["wrong_count"] == 1
    assert "wrong_count" in change["changed_fields"]

    # Verify DB state
    wp = db_session.query(WeakPoint).filter(
        WeakPoint.knowledge_point_id == kp.id
    ).first()
    assert wp is not None
    assert wp.wrong_count == 1
    assert wp.status == "active"


def test_weak_point_increment_explained(db_session, sample_user, sample_course):
    """Second wrong answer increments with explanation."""
    kp = KnowledgePoint(
        course_id=sample_course.id,
        user_id=sample_user.id,
        title="测试知识点",
        source_chunk_ids="[]",
        status="active",
    )
    db_session.add(kp)
    db_session.flush()

    # First wrong answer — creates the weak point
    _upsert_weak_point(
        db_session,
        user_id=sample_user.id,
        course_id=sample_course.id,
        knowledge_point_id=kp.id,
        correct=False,
    )

    # Second wrong answer — increments
    change = _upsert_weak_point(
        db_session,
        user_id=sample_user.id,
        course_id=sample_course.id,
        knowledge_point_id=kp.id,
        correct=False,
    )

    assert change["action"] == "updated"
    assert change["previous"]["wrong_count"] == 1
    assert change["current"]["wrong_count"] == 2
    assert "wrong_count" in change["changed_fields"]


def test_weak_point_correct_answer_explained(db_session, sample_user, sample_course):
    """Correct answer updates correct_count."""
    kp = KnowledgePoint(
        course_id=sample_course.id,
        user_id=sample_user.id,
        title="测试知识点",
        source_chunk_ids="[]",
        status="active",
    )
    db_session.add(kp)
    db_session.flush()

    # Create weak point with wrong answer
    _upsert_weak_point(
        db_session,
        user_id=sample_user.id,
        course_id=sample_course.id,
        knowledge_point_id=kp.id,
        correct=False,
    )

    # Now answer correctly
    change = _upsert_weak_point(
        db_session,
        user_id=sample_user.id,
        course_id=sample_course.id,
        knowledge_point_id=kp.id,
        correct=True,
    )

    assert change["action"] == "updated"
    assert change["correct"] is True
    assert change["previous"]["correct_count"] == 0
    assert change["current"]["correct_count"] == 1
    assert "correct_count" in change["changed_fields"]
    assert "mastery_score" in change["changed_fields"]


def test_weak_point_resolution_explained(db_session, sample_user, sample_course):
    """3 consecutive correct -> status changes to 'resolved'."""
    kp = KnowledgePoint(
        course_id=sample_course.id,
        user_id=sample_user.id,
        title="测试知识点",
        source_chunk_ids="[]",
        status="active",
    )
    db_session.add(kp)
    db_session.flush()

    # Create weak point with wrong answer (mastery=0, status=active)
    _upsert_weak_point(
        db_session,
        user_id=sample_user.id,
        course_id=sample_course.id,
        knowledge_point_id=kp.id,
        correct=False,
    )

    # Manually set mastery to 20 so 3 correct answers reach >= 70
    wp = db_session.query(WeakPoint).filter(
        WeakPoint.knowledge_point_id == kp.id
    ).first()
    wp.mastery_score = 20
    db_session.flush()

    # Three consecutive correct answers
    changes = []
    for _ in range(3):
        change = _upsert_weak_point(
            db_session,
            user_id=sample_user.id,
            course_id=sample_course.id,
            knowledge_point_id=kp.id,
            correct=True,
        )
        changes.append(change)

    # After 3 consecutive correct: mastery 20->40->60->80, consecutive 0->1->2->3
    # mastery >= 70 and consecutive >= 3 -> resolved
    final_change = changes[-1]
    assert final_change["current"]["status"] == "resolved"
    assert "status" in final_change["changed_fields"]
    assert final_change["current"]["consecutive_correct"] == 3


def test_weak_point_mastery_recalculated(db_session, sample_user, sample_course):
    """mastery_score changes are explained."""
    kp = KnowledgePoint(
        course_id=sample_course.id,
        user_id=sample_user.id,
        title="测试知识点",
        source_chunk_ids="[]",
        status="active",
    )
    db_session.add(kp)
    db_session.flush()

    # Create with wrong answer
    create_change = _upsert_weak_point(
        db_session,
        user_id=sample_user.id,
        course_id=sample_course.id,
        knowledge_point_id=kp.id,
        correct=False,
    )

    # mastery_score should be 0 after wrong answer
    assert create_change["current"]["mastery_score"] == 0

    # Answer correctly — mastery should increase
    update_change = _upsert_weak_point(
        db_session,
        user_id=sample_user.id,
        course_id=sample_course.id,
        knowledge_point_id=kp.id,
        correct=True,
    )

    assert "mastery_score" in update_change["changed_fields"]
    assert update_change["previous"]["mastery_score"] == 0
    assert update_change["current"]["mastery_score"] == 20  # 0 + 20
