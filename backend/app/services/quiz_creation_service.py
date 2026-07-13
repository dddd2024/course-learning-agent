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
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from sqlalchemy.orm import Session

from app.agents.quiz import generate_quiz
from app.core.exceptions import BusinessException, QuizConstraintException
from app.models.quiz import Quiz, QuizItem
from app.services.llm_config_service import build_user_config, get_active_config

logger = logging.getLogger(__name__)

_DEFAULT_PASS_SCORE = 60

# V7.4.2-03: Default contract constants
_DEFAULT_QUESTION_TYPES = ["choice", "true_false", "short_answer"]
_DEFAULT_DIFFICULTY_DISTRIBUTION = {"easy": 3, "medium": 5, "hard": 2}
_MAX_RETRIES = 2


@dataclass(frozen=True)
class QuizContract:
    question_count: int
    question_types: tuple[str, ...]
    difficulty_distribution: MappingProxyType
    pass_score: int


def resolve_quiz_contract(question_count: int, question_types: list[str] | None, difficulty_distribution: dict[str, int] | None, pass_score: int) -> QuizContract:
    """Resolve every creation input once, before any provider is invoked."""
    if question_count < 1:
        raise BusinessException(message="题目数量必须大于 0", status_code=422)
    if not 0 <= pass_score <= 100:
        raise BusinessException(message="及格线必须在 0 到 100 之间", status_code=422)
    types = tuple(question_types or _DEFAULT_QUESTION_TYPES)
    allowed = {"choice", "multiple_choice", "true_false", "short_answer"}
    if not types or any(item not in allowed for item in types):
        raise BusinessException(message="题型不合法", status_code=422)
    if difficulty_distribution is None:
        # Deterministic round-robin allocation keeps the three bands summing
        # exactly to question_count for every requested size.
        distribution = {band: 0 for band in ("easy", "medium", "hard")}
        for index in range(question_count):
            distribution[("easy", "medium", "hard")[index % 3]] += 1
    else:
        distribution = {band: int(difficulty_distribution.get(band, 0)) for band in ("easy", "medium", "hard")}
        if any(value < 0 for value in distribution.values()) or sum(distribution.values()) != question_count:
            raise BusinessException(message="难度分布总和必须等于题目数量", status_code=422)
    return QuizContract(question_count, types, MappingProxyType(distribution), pass_score)


def _item_identity(item: dict) -> tuple:
    """Use normalized stem, knowledge point and evidence for cross-round dedupe."""
    evidence = tuple(sorted(str(entry.get("chunk_id")) for entry in item.get("source_evidence", []) if isinstance(entry, dict)))
    return (re.sub(r"\s+", " ", str(item.get("question_text", "")).strip().lower()), item.get("knowledge_point_id"), evidence)


def _is_acceptable_item(item: dict, contract: QuizContract, remaining: dict[str, int], seen: set[tuple]) -> bool:
    identity = _item_identity(item)
    band = _difficulty_band(item)
    return bool(
        item.get("question_type") in contract.question_types
        and remaining.get(band, 0) > 0
        and item.get("knowledge_point_id") is not None
        and item.get("source_evidence")
        and identity[0]
        and identity not in seen
    )


class QuizCreationService:
    """Unified service for creating quizzes with strict contract enforcement."""

    # V7.4.2-03: Expose default contract as class attributes
    DEFAULT_PASS_SCORE = _DEFAULT_PASS_SCORE
    DEFAULT_QUESTION_TYPES = _DEFAULT_QUESTION_TYPES
    DEFAULT_DIFFICULTY_DISTRIBUTION = _DEFAULT_DIFFICULTY_DISTRIBUTION
    MAX_RETRIES = _MAX_RETRIES

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
        contract = resolve_quiz_contract(question_count, question_types, difficulty_distribution, pass_score)
        question_count = contract.question_count
        question_types = list(contract.question_types)
        difficulty_distribution = dict(contract.difficulty_distribution)
        pass_score = contract.pass_score
        if not knowledge_points:
            raise BusinessException(
                message="课程暂无知识点，请先生成知识点",
                status_code=422,
            )

        # Validate generation consistency and active status
        # V7.4.2-07: Reject KPs from archived (non-active) generations.
        active_generation = max(kp.generation for kp in knowledge_points)
        if any(kp.generation != active_generation for kp in knowledge_points):
            raise QuizConstraintException(
                requested_count=question_count,
                valid_count=0,
                drop_reasons=["knowledge_point_not_in_active_generation"],
            )

        # V7.4.2-07: Verify the generation matches the DB's current active generation
        try:
            from app.models.knowledge_point import KnowledgePoint as KPModel
            db_active_gen = (
                db.query(KPModel.generation)
                .filter(
                    KPModel.course_id == course_id,
                    KPModel.status == "active",
                )
                .order_by(KPModel.generation.desc())
                .first()
            )
            if db_active_gen and isinstance(db_active_gen[0], int) and db_active_gen[0] != active_generation:
                raise QuizConstraintException(
                    requested_count=question_count,
                    valid_count=0,
                    drop_reasons=["knowledge_point_from_archived_generation"],
                )
        except QuizConstraintException:
            raise
        except Exception:
            pass

        # Resolve LLM config if not provided
        if user_config is None:
            active_config = get_active_config(db, user_id)
            user_config = build_user_config(active_config) if active_config else None

        # The service owns gap retries. Every retry receives only the remaining
        # count and difficulty vector; accepted items from an earlier round are
        # never discarded or sent back through the provider.
        items: list[dict] = []
        seen: set[tuple] = set()
        remaining = dict(contract.difficulty_distribution)
        reasons: list[str] = []
        quiz_output: dict = {}
        for attempt in range(QuizCreationService.MAX_RETRIES + 1):
            requested_count = sum(remaining.values())
            if not requested_count:
                break
            quiz_output = generate_quiz(
                db=db, user_id=user_id, course_id=course_id, knowledge_points=knowledge_points,
                course_name=course_name, question_count=requested_count,
                question_types=question_types, difficulty_distribution=remaining, user_config=user_config,
            )
            reasons.extend(quiz_output.get("drop_reasons") or [])
            accepted = 0
            for candidate in quiz_output.get("items") or []:
                if _is_acceptable_item(candidate, contract, remaining, seen):
                    band = _difficulty_band(candidate)
                    seen.add(_item_identity(candidate))
                    remaining[band] -= 1
                    candidate["order_index"] = len(items)
                    items.append(candidate)
                    accepted += 1
            logger.info("quiz contract retry attempt=%d deficit=%s retained=%d accepted=%d", attempt, remaining, len(items), accepted)
        if sum(remaining.values()):
            raise QuizConstraintException(
                requested_count=question_count, valid_count=len(items),
                drop_reasons=list(dict.fromkeys(reasons or ["contract_deficit_after_retries"])),
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
