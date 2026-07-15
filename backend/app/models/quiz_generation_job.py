"""Durable asynchronous quiz-generation jobs."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class QuizGenerationJob(Base, TimestampMixin):
    __tablename__ = "quiz_generation_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("study_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)
    progress_stage = Column(String(40), nullable=False, default="preparing")
    payload_json = Column(Text, nullable=False)
    provider_calls = Column(Integer, nullable=False, default=0)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True, index=True)
    finished_at = Column(DateTime, nullable=True)
