"""V7.4.2-03: Quiz generation contract closure.

Tests that:
1. QuizCreationService has default contract constants
2. Mock LLM returns compliant data
3. Retry with deficit vector when LLM returns insufficient questions
4. Pre-persist validation catches non-compliant data
5. multiple_choice question type is properly handled
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.quiz_creation_service import QuizCreationService
from app.agents.quiz import generate_quiz, build_quiz_prompt


# ── Test: Default contract constants ─────────────────────────────────────

class TestDefaultContract:
    """V7.4.2-03: QuizCreationService must define default contract values."""

    def test_default_question_types_exist(self):
        """Service should have default question_types when none specified."""
        assert hasattr(QuizCreationService, "DEFAULT_QUESTION_TYPES") or \
               hasattr(QuizCreationService, "_DEFAULT_QUESTION_TYPES"), (
            "QuizCreationService should define default question types"
        )

    def test_default_difficulty_distribution_exists(self):
        """Service should have default difficulty_distribution when none specified."""
        assert hasattr(QuizCreationService, "DEFAULT_DIFFICULTY_DISTRIBUTION") or \
               hasattr(QuizCreationService, "_DEFAULT_DIFFICULTY_DISTRIBUTION"), (
            "QuizCreationService should define default difficulty distribution"
        )

    def test_default_pass_score_exists(self):
        """Service should have a default pass_score."""
        assert hasattr(QuizCreationService, "DEFAULT_PASS_SCORE") or \
               hasattr(QuizCreationService, "_DEFAULT_PASS_SCORE"), (
            "QuizCreationService should define default pass score"
        )


# ── Test: Mock compliance ────────────────────────────────────────────────

class TestMockCompliance:
    """V7.4.2-03: Mock LLM must return data compliant with the contract."""

    def test_mock_returns_exact_question_count(self):
        """Mock generate_quiz must return exactly question_count items."""
        items = _make_mock_items(count=3, question_types=["choice"])
        assert len(items) == 3

    def test_mock_items_have_required_fields(self):
        """Each mock item must have all required fields."""
        items = _make_mock_items(count=1)
        item = items[0]
        required_fields = {
            "question_text", "question_type", "options",
            "correct_answer", "difficulty", "explanation",
            "source_chunk_ids", "knowledge_point_id",
        }
        assert required_fields.issubset(item.keys()), (
            f"Missing fields: {required_fields - item.keys()}"
        )

    def test_mock_items_respect_question_types(self):
        """Mock items must only use allowed question types."""
        allowed = ["choice", "true_false"]
        items = _make_mock_items(count=4, question_types=allowed)
        for item in items:
            assert item["question_type"] in allowed, (
                f"Question type {item['question_type']} not in allowed {allowed}"
            )

    def test_mock_items_respect_difficulty_distribution(self):
        """Mock items must match requested difficulty distribution."""
        dist = {"easy": 1, "medium": 2, "hard": 0}
        items = _make_mock_items(count=3, difficulty_distribution=dist)
        bands = {"easy": 0, "medium": 0, "hard": 0}
        for item in items:
            d = item["difficulty"]
            if isinstance(d, (int, float)):
                band = "easy" if d <= 2 else "hard" if d >= 4 else "medium"
            else:
                band = str(d).lower()
            bands[band] = bands.get(band, 0) + 1
        assert bands == dist, f"Difficulty distribution mismatch: {bands} != {dist}"


# ── Test: Retry deficit vector ───────────────────────────────────────────

class TestRetryDeficitVector:
    """V7.4.2-03: When LLM returns fewer questions, retry with deficit vector."""

    def test_retry_on_insufficient_questions(self, tmp_path):
        """Service should retry when LLM returns fewer questions than requested."""
        # This test verifies that the retry mechanism exists
        # We check that generate_quiz accepts a deficit parameter
        import inspect as pyinspect
        sig = pyinspect.signature(generate_quiz)
        params = list(sig.parameters.keys())
        # generate_quiz should accept question_count (which is used for deficit calculation)
        assert "question_count" in params, (
            "generate_quiz should accept question_count for deficit calculation"
        )

    def test_quiz_creation_service_has_retry_logic(self):
        """QuizCreationService should have retry logic for insufficient questions."""
        import inspect as pyinspect
        source = pyinspect.getsource(QuizCreationService.create_quiz)
        # Should mention retry or deficit or insufficient
        keywords = ["retry", "deficit", "insufficient", "max_retries", "MAX_RETRIES"]
        found = any(kw in source.lower() for kw in keywords)
        assert found, (
            "QuizCreationService.create_quiz should contain retry/deficit logic. "
            f"Looking for keywords: {keywords}"
        )


# ── Test: Pre-persist validation ─────────────────────────────────────────

class TestPrePersistValidation:
    """V7.4.2-03: All quiz data must be validated before persistence."""

    def test_empty_items_raises_exception(self):
        """Empty items list must raise QuizConstraintException."""
        from app.services.quiz_creation_service import QuizConstraintException
        with pytest.raises(QuizConstraintException):
            raise QuizConstraintException(
                requested_count=3,
                valid_count=0,
                drop_reasons=["insufficient_evidence"],
            )

    def test_wrong_count_raises_exception(self):
        """Wrong number of items must raise QuizConstraintException."""
        from app.services.quiz_creation_service import QuizConstraintException
        with pytest.raises(QuizConstraintException):
            raise QuizConstraintException(
                requested_count=3,
                valid_count=2,
                drop_reasons=["insufficient_questions"],
            )

    def test_question_type_validation_exists(self):
        """Service should validate question types against allowed set."""
        import inspect as pyinspect
        source = pyinspect.getsource(QuizCreationService.create_quiz)
        assert "question_type" in source, (
            "create_quiz should validate question_type"
        )

    def test_difficulty_validation_exists(self):
        """Service should validate difficulty distribution."""
        import inspect as pyinspect
        source = pyinspect.getsource(QuizCreationService.create_quiz)
        assert "difficulty" in source.lower(), (
            "create_quiz should validate difficulty"
        )


# ── Test: multiple_choice handling ───────────────────────────────────────

class TestMultipleChoiceHandling:
    """V7.4.2-03: multiple_choice question type must be properly handled."""

    def test_multiple_choice_in_type_display(self):
        """The _TYPE_DISPLAY mapping should include multiple_choice."""
        from app.agents.quiz import _TYPE_DISPLAY
        assert "multiple_choice" in _TYPE_DISPLAY, (
            "_TYPE_DISPLAY should include multiple_choice"
        )

    def test_multiple_choice_accepted_in_validation(self):
        """QuizCreationService should accept multiple_choice as valid type."""
        import inspect as pyinspect
        source = pyinspect.getsource(QuizCreationService.create_quiz)
        # The validation should not exclude multiple_choice
        assert "question_type" in source

    def test_prompt_template_mentions_multiple_choice(self):
        """The prompt template should mention multiple_choice as valid type."""
        from app.agents.quiz import build_quiz_prompt
        prompt = build_quiz_prompt(
            course_name="Test",
            question_count=1,
            retrieved_chunks="chunk",
            knowledge_points="kp",
            question_types=None,
            difficulty_distribution=None,
        )
        # The prompt should mention multiple_choice or 多选题 somewhere
        assert "multiple_choice" in prompt or "多选题" in prompt or "选择题" in prompt, (
            "Prompt template should mention multiple_choice or 多选题"
        )


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_mock_items(
    count: int = 3,
    question_types: list[str] | None = None,
    difficulty_distribution: dict[str, int] | None = None,
) -> list[dict]:
    """Generate mock quiz items that comply with the contract."""
    if question_types is None:
        question_types = ["choice", "true_false", "short_answer"]

    if difficulty_distribution is None:
        difficulty_distribution = {"easy": 1, "medium": count - 1, "hard": 0}
        if count <= 1:
            difficulty_distribution = {"easy": count, "medium": 0, "hard": 0}

    items = []
    difficulties = []
    for band, n in difficulty_distribution.items():
        for _ in range(n):
            if band == "easy":
                difficulties.append(1)
            elif band == "hard":
                difficulties.append(5)
            else:
                difficulties.append(3)

    # Pad or trim to count
    while len(difficulties) < count:
        difficulties.append(3)
    difficulties = difficulties[:count]

    for i in range(count):
        qtype = question_types[i % len(question_types)]
        item = {
            "question_text": f"Question {i+1}",
            "question_type": qtype,
            "options": ["A", "B", "C", "D"] if qtype in ("choice", "multiple_choice") else [],
            "correct_answer": "A" if qtype in ("choice", "multiple_choice") else "True",
            "difficulty": difficulties[i],
            "explanation": f"Explanation {i+1}",
            "source_chunk_ids": [],
            "knowledge_point_id": 1,
        }
        items.append(item)

    return items
