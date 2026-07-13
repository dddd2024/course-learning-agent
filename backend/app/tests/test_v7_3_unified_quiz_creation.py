"""V7.3-02 P0-03: Unified quiz creation service.

Tests that all quiz creation paths enforce the same strict contract:
partial quizzes are rejected, question count must match, and plan task
quiz creation uses the unified service.
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from app.core.exceptions import QuizConstraintException, BusinessException


def test_quiz_creation_service_exists_and_is_importable():
    """QuizCreationService must exist in the services package."""
    from app.services.quiz_creation_service import QuizCreationService
    assert QuizCreationService is not None


def test_quiz_creation_service_rejects_partial_quiz():
    """When generate_quiz returns fewer items than requested, reject."""
    from app.services.quiz_creation_service import QuizCreationService

    mock_db = MagicMock()
    mock_kp = MagicMock()
    mock_kp.id = 1
    mock_kp.generation = 1
    mock_kp.course_id = 1
    mock_kp.user_id = 1
    mock_kp.status = "active"
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (1,)
    mock_kp.course_id = 1
    mock_kp.user_id = 1
    mock_kp.status = "active"
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (1,)

    with patch("app.services.quiz_creation_service.generate_quiz") as mock_gen:
        mock_gen.return_value = {
            "items": [
                {"question_type": "choice", "question_text": "Q1", "answer": "A",
                 "options": ["A", "B"], "knowledge_point_id": 1, "difficulty": 1,
                 "order_index": 0, "explanation": "exp", "source_evidence_ids": [1],
                 "source_evidence": [{"chunk_id": 1, "quote_text": "source"}], "verification_status": "verified", "rubric": []},
            ],
            "title": "Test Quiz",
        }
        with pytest.raises(QuizConstraintException):
            QuizCreationService.create_quiz(
                db=mock_db,
                user_id=1,
                course_id=1,
                course_name="Test",
                knowledge_points=[mock_kp],
                question_count=5,
                pass_score=60,
                user_config={"model": "test"},
            )


def test_task_quiz_creation_uses_unified_service():
    """_create_quiz_for_task must delegate to QuizCreationService."""
    import inspect
    from app.services import task_execution_service

    source = inspect.getsource(task_execution_service._create_quiz_for_task)
    assert "QuizCreationService" in source or "quiz_creation_service" in source


def test_plan_task_has_target_spec():
    """StudyTask model must have target_spec_json column."""
    from app.models.plan import StudyTask
    assert hasattr(StudyTask, 'target_spec_json')


def test_quiz_creation_service_enforces_question_types():
    """When question_types constraint is set, items must match types."""
    from app.services.quiz_creation_service import QuizCreationService

    mock_db = MagicMock()
    mock_kp = MagicMock()
    mock_kp.id = 1
    mock_kp.generation = 1
    mock_kp.course_id = 1
    mock_kp.user_id = 1
    mock_kp.status = "active"
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (1,)
    mock_kp.course_id = 1
    mock_kp.user_id = 1
    mock_kp.status = "active"
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (1,)

    with patch("app.services.quiz_creation_service.generate_quiz") as mock_gen:
        mock_gen.return_value = {
            "items": [
                {"question_type": "short_answer", "question_text": "Q1", "answer": "A1",
                 "knowledge_point_id": 1, "difficulty": 3, "order_index": 0,
                 "options": [], "explanation": "", "source_evidence_ids": [],
                 "source_evidence": [], "verification_status": "verified", "rubric": []},
            ],
            "title": "Test Quiz",
        }
        with pytest.raises(QuizConstraintException):
            QuizCreationService.create_quiz(
                db=mock_db,
                user_id=1,
                course_id=1,
                course_name="Test",
                knowledge_points=[mock_kp],
                question_count=1,
                pass_score=60,
                question_types=["choice"],
                user_config={"model": "test"},
            )


def test_quiz_creation_service_persists_quiz_and_items():
    """QuizCreationService must create Quiz and QuizItem rows."""
    from app.services.quiz_creation_service import QuizCreationService
    from app.models.quiz import Quiz, QuizItem

    mock_db = MagicMock()
    mock_kp = MagicMock()
    mock_kp.id = 1
    mock_kp.generation = 1
    mock_kp.course_id = 1
    mock_kp.user_id = 1
    mock_kp.status = "active"
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (1,)

    with patch("app.services.quiz_creation_service.generate_quiz") as mock_gen:
        mock_gen.return_value = {
            "items": [
                {"question_type": "choice", "question_text": "Q1", "answer": "A",
                 "options": ["A", "B"], "knowledge_point_id": 1, "difficulty": 1,
                 "order_index": 0, "explanation": "exp", "source_evidence_ids": [1],
                 "source_evidence": [{"chunk_id": 1, "quote_text": "source"}], "verification_status": "verified", "rubric": []},
            ],
            "title": "Test Quiz",
        }
        result = QuizCreationService.create_quiz(
            db=mock_db,
            user_id=1,
            course_id=1,
            course_name="Test",
            knowledge_points=[mock_kp],
            question_count=1,
            pass_score=70,
            user_config={"model": "test"},
        )
        assert result is not None
        assert mock_db.add.call_count >= 2
        mock_db.flush.assert_called()


def test_quiz_creation_service_passes_pass_score():
    """QuizCreationService must persist the pass_score."""
    from app.services.quiz_creation_service import QuizCreationService

    mock_db = MagicMock()
    mock_kp = MagicMock()
    mock_kp.id = 1
    mock_kp.generation = 1
    mock_kp.course_id = 1
    mock_kp.user_id = 1
    mock_kp.status = "active"
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (1,)

    with patch("app.services.quiz_creation_service.generate_quiz") as mock_gen:
        mock_gen.return_value = {
            "items": [
                {"question_type": "choice", "question_text": "Q1", "answer": "A",
                 "options": ["A", "B"], "knowledge_point_id": 1, "difficulty": 1,
                 "order_index": 0, "explanation": "exp", "source_evidence_ids": [1],
                 "source_evidence": [{"chunk_id": 1, "quote_text": "source"}], "verification_status": "verified", "rubric": []},
            ],
            "title": "Test Quiz",
        }
        result = QuizCreationService.create_quiz(
            db=mock_db,
            user_id=1,
            course_id=1,
            course_name="Test",
            knowledge_points=[mock_kp],
            question_count=1,
            pass_score=80,
            user_config={"model": "test"},
        )
        quiz_obj = mock_db.add.call_args_list[0][0][0]
        assert quiz_obj.pass_score == 80


def test_quiz_creation_service_rejects_empty_knowledge_points():
    """Empty knowledge_points must raise BusinessException."""
    from app.services.quiz_creation_service import QuizCreationService

    mock_db = MagicMock()
    with pytest.raises(BusinessException):
        QuizCreationService.create_quiz(
            db=mock_db,
            user_id=1,
            course_id=1,
            course_name="Test",
            knowledge_points=[],
            question_count=5,
            pass_score=60,
            user_config={"model": "test"},
        )


def test_quiz_creation_service_rejects_generation_mismatch():
    """Knowledge points from different generations must be rejected."""
    from app.services.quiz_creation_service import QuizCreationService

    mock_db = MagicMock()
    kp1 = MagicMock()
    kp1.id = 1
    kp1.generation = 1
    kp2 = MagicMock()
    kp2.id = 2
    kp2.generation = 2

    with pytest.raises(QuizConstraintException):
        QuizCreationService.create_quiz(
            db=mock_db,
            user_id=1,
            course_id=1,
            course_name="Test",
            knowledge_points=[kp1, kp2],
            question_count=5,
            pass_score=60,
            user_config={"model": "test"},
        )
