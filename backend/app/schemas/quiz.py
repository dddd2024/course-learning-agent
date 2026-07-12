"""Pydantic schemas for the quiz and weak-point endpoints."""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SUPPORTED_QUESTION_TYPES = frozenset({"choice", "multiple_choice", "true_false", "short_answer"})
SUPPORTED_DIFFICULTIES = frozenset({"easy", "medium", "hard"})


class QuizCreate(BaseModel):
    """Payload for POST /quizzes."""

    course_id: int
    knowledge_point_ids: Optional[List[int]] = None
    question_count: int = Field(default=5, ge=1, le=30)
    question_types: Optional[List[str]] = Field(default=None, min_length=1)
    difficulty_distribution: Optional[dict[str, int]] = None
    pass_score: int = Field(default=60, ge=0, le=100)

    @field_validator("question_types")
    @classmethod
    def _valid_question_types(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return value
        normalized = list(dict.fromkeys(item.strip() for item in value))
        if not normalized or any(item not in SUPPORTED_QUESTION_TYPES for item in normalized):
            raise ValueError("question_types 仅允许 choice/multiple_choice/true_false/short_answer")
        return normalized

    @model_validator(mode="after")
    def _valid_difficulty_distribution(self) -> "QuizCreate":
        if self.difficulty_distribution is None:
            return self
        if (
            not self.difficulty_distribution
            or any(name not in SUPPORTED_DIFFICULTIES or count < 0 for name, count in self.difficulty_distribution.items())
            or sum(self.difficulty_distribution.values()) != self.question_count
        ):
            raise ValueError("difficulty_distribution 必须由 easy/medium/hard 组成且总数等于 question_count")
        return self


class QuizOption(BaseModel):
    label: str
    text: str
    value: str


class QuizItemOut(BaseModel):
    """A single quiz item returned to the client.

    Note: ``answer`` is intentionally excluded so the client cannot
    cheat by reading the correct answer before submitting.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    question_type: str
    question_text: str
    options: List[QuizOption] = []
    explanation: Optional[str] = None
    order_index: int
    # QUIZ-V3-01: source evidence with chunk_id and quote_text for grounding.
    source_evidence: List[dict] = []
    # QUIZ-V3-02: verification status of this quiz item.
    verification_status: str = "verified"

    @field_validator("options", mode="before")
    @classmethod
    def _parse_options(cls, value):
        """Parse the JSON string stored in the DB into a list."""
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                value = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        if value is None:
            return []
        result = []
        for index, option in enumerate(value):
            if isinstance(option, dict):
                result.append(option)
            else:
                raw = str(option)
                label = raw[:1].upper() if len(raw) > 1 and raw[1] in ".、)" else chr(65 + index)
                text = raw[2:].strip() if len(raw) > 1 and raw[1] in ".、)" else raw
                result.append({"label": label, "text": text, "value": label})
        return result

    @field_validator("source_evidence", mode="before")
    @classmethod
    def _parse_source_evidence(cls, value):
        """Parse the JSON string stored in the DB into a list."""
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                value = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        if value is None:
            return []
        return value


class QuizOut(BaseModel):
    """A quiz with its items (answers excluded)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    title: str
    question_count: int
    status: str
    score: Optional[int] = None
    created_at: Optional[datetime] = None
    items: List[QuizItemOut] = []
    # QUIZ-V3-01: flag for quizzes with no evidence-backed items.
    insufficient_evidence: bool = False
    # QUIZ-V3-02: flag when some items were dropped during verification.
    partial_generation: bool = False


class QuizListResponse(BaseModel):
    """List of quizzes for the current user."""

    items: List[QuizOut]
    total: int


class QuizSubmitAnswer(BaseModel):
    """A single answer in a submit payload."""

    item_id: int
    user_answer: str | List[str]


class QuizSubmit(BaseModel):
    """Payload for POST /quizzes/{id}/submit."""

    answers: List[QuizSubmitAnswer]
    # V6-23: optional task_id to auto-verify a bound quiz task on submit.
    task_id: Optional[int] = None


class QuizResultItemOut(BaseModel):
    """A graded quiz item returned after submit.

    Unlike ``QuizItemOut`` (used before submit), this one DOES expose the
    ``correct_answer`` so the client can render the right answer next to
    the user's answer in the review screen.

    QUIZ-V3-03: ``rubric_feedback`` now includes per-criterion details
    (weight, score, hit_keywords, missing_keywords) and a total score
    summary entry when using weighted rubrics.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    question_type: str
    question_text: str
    options: List[QuizOption] = []
    correct_answer: str = ""
    user_answer: Optional[str] = None
    is_correct: Optional[bool] = None
    explanation: Optional[str] = None
    knowledge_point_id: Optional[int] = None
    rubric_feedback: List[dict] = []
    needs_review: bool = False
    # QUIZ-V3-01: source evidence in result items.
    source_evidence: List[dict] = []
    # QUIZ-V3-02: verification status.
    verification_status: str = "verified"

    @field_validator("options", mode="before")
    @classmethod
    def _parse_options(cls, value):
        """Parse the JSON string stored in the DB into a list."""
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                value = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        return QuizItemOut._parse_options(value)

    @field_validator("source_evidence", mode="before")
    @classmethod
    def _parse_source_evidence(cls, value):
        """Parse the JSON string stored in the DB into a list."""
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                value = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        if value is None:
            return []
        return value


class QuizResultOut(BaseModel):
    """Result of POST /quizzes/{id}/submit."""

    id: int
    score: int
    total: int
    items: List[QuizResultItemOut]
    # V6-32: explainable weak point changes from this submission.
    weak_point_changes: List[dict] = []


class WeakPointOut(BaseModel):
    """A weak point with the knowledge-point title denormalised."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    knowledge_point_id: int
    knowledge_point_title: str = ""
    wrong_count: int
    last_wrong_at: Optional[datetime] = None
    correct_count: int = 0
    consecutive_correct: int = 0
    mastery_score: int = 0
    status: str = "active"
    last_mastery_decay_at: Optional[datetime] = None


class WeakPointListResponse(BaseModel):
    """List of weak points for a course."""

    items: List[WeakPointOut]
    total: int
