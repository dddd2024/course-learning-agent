"""V7.3-02 P0-03: Unified quiz creation service.

All quiz creation paths (endpoint, plan task, future callers) delegate
to this service so that the strict contract is enforced uniformly:

- Partial quizzes (fewer items than requested) are rejected.
- Question type constraints are validated.
- Difficulty distribution constraints are validated.
- Pass score is persisted on the Quiz row.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.agents.quiz import generate_quiz
from app.core.exceptions import BusinessException, QuizConstraintException
from app.models.quiz import Quiz, QuizItem
from app.services.llm_config_service import build_user_config, get_active_config

logger = logging.getLogger(__name__)

_DEFAULT_PASS_SCORE = 60


class QuizCreationService:
    """Unified service for creating quizzes with strict contract enforcement."""

    @staticmethod
    def create_quiz(
        db: Session,
        user_id: int,
        course_id: int,
        course_name: str,
        knowledge_points: list,
        question_count: int,
        pass_score: int = _DEFAULT_PASS_SCORE,
        question_types: list[str] | None = None,
        difficulty_distribution: dict[str, int] | None = None,
        user_config: dict | None = None,
    ) -> Quiz:
        """Create a quiz with strict contract enforcement.

        Args:
            db: Database session.
            user_id: Owner of the quiz.
            course_id: Course the quiz belongs to.
            course_name: Display name for title generation.
            knowledge_points: Active KnowledgePoint rows to quiz on.
            question_count: Exact number of questions requested.
            pass_score: Minimum passing score (0-100).
            question_types: Optional list of allowed question types.
            difficulty_distribution: Optional {easy, medium, hard} counts.
            user_config: Optional LLM config dict.

        Returns:
            The persisted Quiz object with items.

        Raises:
            QuizConstraintException: If constraints are not satisfied.
            BusinessException: If no knowledge points or evidence.
        """
        if not knowledge_points:
            raise BusinessException(
                message="课程暂无知识点，请先生成知识点",
                status_code=422,
            )

        # Validate generation consistency
        active_generation = max(kp.generation for kp in knowledge_points)
        if any(kp.generation != active_generation for kp in knowledge_points):
            raise QuizConstraintException(
                requested_count=question_count,
                valid_count=0,
                drop_reasons=["knowledge_point_not_in_active_generation"],
            )

        # Resolve LLM config if not provided
        if user_config is None:
            active_config = get_active_config(db, user_id)
            user_config = build_user_config(active_config) if active_config else None

        # Generate quiz items
        # V7.4.1-03: forward the requested question_types and
        # difficulty_distribution so they propagate into the LLM prompt.
        quiz_output = generate_quiz(
            db=db,
            user_id=user_id,
            course_id=course_id,
            knowledge_points=knowledge_points,
            course_name=course_name,
            question_count=question_count,
            question_types=question_types,
            difficulty_distribution=difficulty_distribution,
            user_config=user_config,
        )

        insufficient_evidence = quiz_output.get("insufficient_evidence", False)
        items = quiz_output.get("items") or []
        reasons = list(quiz_output.get("drop_reasons") or [])

        # P0-03: Always enforce strict count — reject partial quizzes
        if not items:
            raise QuizConstraintException(
                requested_count=question_count,
                valid_count=0,
                drop_reasons=reasons or ["insufficient_evidence"],
            )
        if len(items) != question_count:
            raise QuizConstraintException(
                requested_count=question_count,
                valid_count=len(items),
                drop_reasons=reasons or [
                    "insufficient_evidence" if insufficient_evidence else "insufficient_questions"
                ],
            )

        # Validate question types if constraint is set
        if question_types is not None and any(
            item.get("question_type") not in question_types for item in items
        ):
            raise QuizConstraintException(
                requested_count=question_count,
                valid_count=0,
                drop_reasons=["question_type_constraint"],
            )

        # Validate difficulty distribution if constraint is set
        if difficulty_distribution is not None:
            observed = {
                name: sum(_difficulty_band(item) == name for item in items)
                for name in ("easy", "medium", "hard")
            }
            requested = {
                name: difficulty_distribution.get(name, 0)
                for name in observed
            }
            if observed != requested:
                raise QuizConstraintException(
                    requested_count=question_count,
                    valid_count=0,
                    drop_reasons=["difficulty_distribution_constraint"],
                )

        # Persist Quiz
        quiz = Quiz(
            user_id=user_id,
            course_id=course_id,
            title=quiz_output.get("title", f"{course_name} 测验"),
            question_count=question_count,
            pass_score=pass_score,
            status="draft",
        )
        db.add(quiz)
        db.flush()

        # Persist QuizItems
        for item_data in items:
            item = QuizItem(
                quiz_id=quiz.id,
                knowledge_point_id=item_data.get("knowledge_point_id"),
                question_type=item_data.get("question_type", "short_answer"),
                question_text=item_data.get("question_text", ""),
                options=json.dumps(item_data.get("options", []), ensure_ascii=False),
                answer=item_data.get("answer", ""),
                explanation=item_data.get("explanation", ""),
                difficulty=item_data.get("difficulty"),
                source_evidence_ids=json.dumps(item_data.get("source_evidence_ids", [])),
                evidence_snapshot=json.dumps(item_data.get("source_evidence_ids", [])),
                source_evidence=json.dumps(
                    item_data.get("source_evidence", []), ensure_ascii=False
                ),
                verification_status=item_data.get("verification_status", "verified"),
                rubric_json=json.dumps(item_data.get("rubric", []), ensure_ascii=False),
                order_index=item_data.get("order_index", 0),
            )
            db.add(item)

        db.flush()
        logger.info(
            "QuizCreationService: created quiz %d with %d items for course %d",
            quiz.id, len(items), course_id,
        )
        return quiz


def _difficulty_band(item: dict) -> str:
    """Classify an item's difficulty into easy/medium/hard."""
    value = item.get("difficulty", 3)
    if isinstance(value, str):
        return value if value in {"easy", "medium", "hard"} else "medium"
    return "easy" if value <= 2 else "hard" if value >= 4 else "medium"
