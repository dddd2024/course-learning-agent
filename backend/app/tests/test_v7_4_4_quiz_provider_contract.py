"""V7.4.4-03 production Mock quiz-contract tests.

These tests intentionally invoke QuizCreationService -> generate_quiz ->
the registered production Mock provider using a real SQLite test database.
They do not fabricate provider items in a helper.
"""
from __future__ import annotations

import json

import pytest

from app.agents import llm
from app.api.v1.endpoints.quizzes import _grade_item
from app.core.config import settings
from app.core.exceptions import QuizConstraintException
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.quiz import Quiz, QuizItem
from app.services.quiz_creation_service import QuizCreationService


EVIDENCE = (
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系，并由操作系统维护。\n"
    "TLB 命中时无需访问内存中的页表，能够提升地址转换速度。"
)


@pytest.fixture()
def quiz_fixture(db_session, sample_user, sample_course, monkeypatch):
    """Persist the minimum real course evidence required by the provider path."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="os-notes.txt",
        file_type="txt",
        file_path="tests/os-notes.txt",
        status="ready",
    )
    db_session.add(material)
    db_session.flush()
    chunk = MaterialChunk(
        material_id=material.id,
        course_id=sample_course.id,
        chunk_index=0,
        text=EVIDENCE,
        raw_text=EVIDENCE,
        is_active=1,
        is_indexable=1,
    )
    db_session.add(chunk)
    db_session.flush()
    point = KnowledgePoint(
        user_id=sample_user.id,
        course_id=sample_course.id,
        title="虚拟内存地址转换",
        summary="TLB 与页表的作用。",
        source_chunk_ids=json.dumps([chunk.id]),
        status="active",
        generation=1,
    )
    db_session.add(point)
    db_session.commit()
    return sample_user, sample_course, point, chunk


def _create(db_session, fixture, question_types, distribution):
    user, course, point, _ = fixture
    quiz = QuizCreationService.create_quiz(
        db=db_session,
        user_id=user.id,
        course_id=course.id,
        course_name=course.name,
        knowledge_points=[point],
        question_count=sum(distribution.values()),
        question_types=question_types,
        difficulty_distribution=distribution,
        pass_score=75,
    )
    db_session.commit()
    db_session.refresh(quiz)
    return quiz


@pytest.mark.parametrize(
    ("question_types", "distribution"),
    [
        (["choice"], {"easy": 1, "medium": 1, "hard": 1}),
        (["multiple_choice"], {"easy": 1, "medium": 1, "hard": 1}),
        (["true_false"], {"easy": 1, "medium": 1, "hard": 1}),
        (["short_answer"], {"easy": 1, "medium": 1, "hard": 1}),
        (["choice", "multiple_choice", "true_false", "short_answer"], {"easy": 2, "medium": 1, "hard": 1}),
    ],
)
def test_production_mock_persists_every_requested_contract(
    db_session, quiz_fixture, question_types, distribution
):
    quiz = _create(db_session, quiz_fixture, question_types, distribution)
    items = sorted(quiz.items, key=lambda item: item.order_index)
    assert quiz.question_count == sum(distribution.values())
    assert quiz.pass_score == 75
    assert len(items) == quiz.question_count
    assert {item.question_type for item in items} == set(question_types)
    assert {
        "easy": sum(item.difficulty == "easy" for item in items),
        "medium": sum(item.difficulty == "medium" for item in items),
        "hard": sum(item.difficulty == "hard" for item in items),
    } == distribution

    for item in items:
        evidence = json.loads(item.source_evidence)
        assert evidence and evidence[0]["quote_text"] in EVIDENCE
        if item.question_type == "choice":
            assert len(json.loads(item.options)) >= 4
            assert isinstance(item.answer, str) and len(item.answer) == 1
        elif item.question_type == "multiple_choice":
            assert len(json.loads(item.options)) >= 4
            assert json.loads(item.answer) == ["A", "B"]
            assert _grade_item(item, ["A", "B"])
            assert not _grade_item(item, ["A"])
        elif item.question_type == "true_false":
            assert item.answer.lower() == "true"
            assert _grade_item(item, True)
        else:
            assert item.answer in EVIDENCE
            assert json.loads(item.rubric_json)


def test_provider_deficit_is_completed_on_the_next_service_round(
    db_session, quiz_fixture, monkeypatch
):
    original = llm._mock_quiz_generate
    calls = 0

    def production_mock_with_first_round_deficit(prompt: str):
        nonlocal calls
        calls += 1
        result = original(prompt)
        # The agent performs one call; the service alone requests the deficit.
        if calls == 1:
            return {**result, "questions": result["questions"][:1]}
        return result

    monkeypatch.setitem(
        llm._MOCK_BUILDERS, "quiz_generate", production_mock_with_first_round_deficit
    )
    quiz = _create(
        db_session, quiz_fixture, ["multiple_choice"],
        {"easy": 1, "medium": 1, "hard": 0},
    )
    assert calls == 2
    assert len(quiz.items) == 2
    assert {item.question_type for item in quiz.items} == {"multiple_choice"}


def test_exhausted_provider_deficit_leaves_no_persisted_quiz(
    db_session, quiz_fixture, monkeypatch
):
    original = llm._mock_quiz_generate

    def production_mock_without_questions(prompt: str):
        result = original(prompt)
        return {**result, "questions": []}

    monkeypatch.setitem(llm._MOCK_BUILDERS, "quiz_generate", production_mock_without_questions)
    with pytest.raises(QuizConstraintException):
        _create(
            db_session, quiz_fixture, ["multiple_choice"],
            {"easy": 1, "medium": 1, "hard": 0},
        )
    assert db_session.query(Quiz).count() == 0
    assert db_session.query(QuizItem).count() == 0
