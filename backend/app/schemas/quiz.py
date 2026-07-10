"""Pydantic schemas for the quiz and weak-point endpoints."""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuizCreate(BaseModel):
    """Payload for POST /quizzes."""

    course_id: int
    knowledge_point_ids: Optional[List[int]] = None
    question_count: int = Field(default=5, ge=1, le=30)


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


class QuizResultItemOut(BaseModel):
    """A graded quiz item returned after submit.

    Unlike ``QuizItemOut`` (used before submit), this one DOES expose the
    ``correct_answer`` so the client can render the right answer next to
    the user's answer in the review screen.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    question_type: str
    question_text: str
    options: List[QuizOption] = []
    correct_answer: str = ""
    user_answer: Optional[str] = None
    is_correct: Optional[int] = None
    explanation: Optional[str] = None
    knowledge_point_id: Optional[int] = None

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


class QuizResultOut(BaseModel):
    """Result of POST /quizzes/{id}/submit."""

    id: int
    score: int
    total: int
    items: List[QuizResultItemOut]


class WeakPointOut(BaseModel):
    """A weak point with the knowledge-point title denormalised."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    knowledge_point_id: int
    knowledge_point_title: str = ""
    wrong_count: int
    last_wrong_at: Optional[datetime] = None


class WeakPointListResponse(BaseModel):
    """List of weak points for a course."""

    items: List[WeakPointOut]
    total: int
