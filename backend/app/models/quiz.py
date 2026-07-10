"""Quiz and weak-point ORM models.

A ``Quiz`` is a generated set of ``QuizItem`` rows for a course. Each
quiz starts in ``draft`` status; submitting answers flips it to
``submitted``, fills in ``score`` / per-item ``user_answer`` /
``is_correct``, and writes ``WeakPoint`` rows for the knowledge points
the user got wrong.

A ``WeakPoint`` records that a user has answered at least one question
linked to a given knowledge point incorrectly. Repeated mistakes
increment ``wrong_count`` and refresh ``last_wrong_at`` so the
``PlannerAgent`` can boost review priority for those points.

All tables are scoped by ``user_id`` so cross-user access is invisible
(returned as 404) by the API layer.
"""
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin


class Quiz(Base, TimestampMixin):
    """A generated quiz belonging to a user and a course."""

    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    course_id = Column(
        Integer, ForeignKey("courses.id"), nullable=False, index=True
    )
    title = Column(String(255), nullable=False)
    question_count = Column(Integer, nullable=False, default=0)
    # Total score, filled on submit (number of correct items).
    score = Column(Integer, nullable=True)
    # draft / submitted
    status = Column(String(20), default="draft", nullable=False)

    items = relationship(
        "QuizItem",
        backref="quiz",
        cascade="all, delete-orphan",
        order_by="QuizItem.order_index",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Quiz id={self.id} title={self.title!r} "
            f"course_id={self.course_id} status={self.status!r}>"
        )


class QuizItem(Base, TimestampMixin):
    """A single question belonging to a ``Quiz``."""

    __tablename__ = "quiz_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    quiz_id = Column(
        Integer, ForeignKey("quizzes.id"), nullable=False, index=True
    )
    knowledge_point_id = Column(
        Integer, ForeignKey("knowledge_points.id"), nullable=True, index=True
    )
    # choice / true_false / short_answer
    question_type = Column(String(30), nullable=False)
    question_text = Column(Text, nullable=False)
    # JSON-serialised list of option strings, e.g. ["A. ...", "B. ..."].
    options = Column(Text)
    # Correct answer (option letter for choice/true_false, reference text
    # for short_answer). Never returned to the client before submit.
    answer = Column(Text, nullable=False)
    explanation = Column(Text)
    difficulty = Column(Integer, nullable=True)
    source_evidence_ids = Column(Text, default="[]")
    evidence_snapshot = Column(Text)
    # Filled on submit.
    user_answer = Column(Text, nullable=True)
    is_correct = Column(Integer, nullable=True)  # 0/1 after submit
    order_index = Column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<QuizItem id={self.id} quiz_id={self.quiz_id} "
            f"question_type={self.question_type!r}>"
        )


class WeakPoint(Base, TimestampMixin):
    """A knowledge point a user has answered wrong at least once."""

    __tablename__ = "weak_points"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "course_id",
            "knowledge_point_id",
            name="uq_weak_points_user_course_kp",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    course_id = Column(
        Integer, ForeignKey("courses.id"), nullable=False, index=True
    )
    knowledge_point_id = Column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    wrong_count = Column(Integer, nullable=False, default=1)
    last_wrong_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<WeakPoint id={self.id} course_id={self.course_id} "
            f"knowledge_point_id={self.knowledge_point_id} "
            f"wrong_count={self.wrong_count}>"
        )
