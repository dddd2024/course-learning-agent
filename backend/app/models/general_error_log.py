"""General ErrorLog ORM model (error-log/parse-reliability plan).

Persists failures and warnings across all categories (upload / parse /
agent / search / system) so the frontend "日志中心" has one diagnostic
surface. Success flows do NOT write here — only failures and warnings.

This is distinct from the existing ``AgentErrorLog`` (Phase 2 Task E),
which is agent-step-specific. Both tables coexist; the new general log
supersedes the agent-only table for the user-facing log center.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class ErrorLog(Base, TimestampMixin):
    """A single failure/warning record for the log center."""

    __tablename__ = "error_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    # upload / parse / agent / search / system
    category = Column(String(30), nullable=False, index=True)
    # warning / error
    level = Column(String(20), nullable=False, default="error")
    # open / resolved / ignored
    status = Column(String(20), nullable=False, default="open", index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    # technical detail (exception type, stack summary) — not shown by default
    technical_detail = Column(Text)
    course_id = Column(Integer, nullable=True, index=True)
    material_id = Column(Integer, nullable=True, index=True)
    agent_run_id = Column(Integer, nullable=True)
    request_path = Column(String(255), nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ErrorLog id={self.id} category={self.category!r} "
            f"level={self.level!r} status={self.status!r}>"
        )
