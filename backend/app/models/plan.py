"""Study-plan and todo ORM models.

A ``StudyGoal`` is a user's learning objective (e.g. "7 天复习完操作系统"),
decomposed by the ``PlannerAgent`` into one or more ``StudyTask`` rows.
The ``scheduler`` service then turns those tasks into per-day ``Todo``
rows that the user works through.

All three tables are scoped by ``user_id`` so cross-user access is
invisible (returned as 404) by the API layer.
"""
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
)

from app.models.base import Base, TimestampMixin


class StudyGoal(Base, TimestampMixin):
    """A user's learning objective plus planning parameters."""

    __tablename__ = "study_goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    title = Column(String(255), nullable=False)
    deadline = Column(Date, nullable=False)
    daily_minutes = Column(Integer, nullable=False, default=120)
    status = Column(String(30), default="active")  # active/done/archived

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<StudyGoal id={self.id} title={self.title!r} "
            f"deadline={self.deadline} user_id={self.user_id}>"
        )


class StudyTask(Base, TimestampMixin):
    """A decomposed stage task belonging to a ``StudyGoal``."""

    __tablename__ = "study_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    goal_id = Column(
        Integer, ForeignKey("study_goals.id"), nullable=False, index=True
    )
    course_id = Column(
        Integer, ForeignKey("courses.id"), nullable=False, index=True
    )
    title = Column(String(255), nullable=False)
    task_type = Column(String(30), nullable=False)  # review/learn/quiz
    estimate_minutes = Column(Integer, nullable=False, default=60)
    priority = Column(Integer, nullable=False, default=3)  # 1-5, 5 highest
    acceptance = Column(Text)
    status = Column(String(30), default="pending")  # pending/done
    target_type = Column(String(30), nullable=True)  # material/knowledge_point/quiz
    target_id = Column(Integer, nullable=True)
    execution_status = Column(String(30), nullable=False, default="pending")
    verification_method = Column(String(50), nullable=True)
    auto_completed_at = Column(DateTime, nullable=True)
    # PLAN-V3-01: executable task target columns
    target_spec_json = Column(Text, nullable=True)  # JSON spec for the task target
    verification_result_json = Column(Text, nullable=True)  # JSON result of verification
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    last_action_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<StudyTask id={self.id} title={self.title!r} "
            f"goal_id={self.goal_id} course_id={self.course_id}>"
        )


class Todo(Base, TimestampMixin):
    """A single day's scheduled work item derived from a ``StudyTask``."""

    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    task_id = Column(
        Integer, ForeignKey("study_tasks.id"), nullable=False, index=True
    )
    course_id = Column(
        Integer, ForeignKey("courses.id"), nullable=False, index=True
    )
    title = Column(String(255), nullable=False)
    scheduled_date = Column(Date, nullable=False, index=True)
    scheduled_start = Column(Time, nullable=True)
    scheduled_end = Column(Time, nullable=True)
    estimate_minutes = Column(Integer, nullable=False, default=60)
    status = Column(String(30), default="pending")
    # pending / completed / postponed / skipped
    actual_minutes = Column(Integer, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Todo id={self.id} title={self.title!r} "
            f"scheduled_date={self.scheduled_date} status={self.status!r}>"
        )
