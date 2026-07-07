"""AgentErrorLog ORM model (Phase 2 Task E).

Persists agent failures (model timeout, retrieval error, save failure)
with enough context to reproduce or diagnose the issue. Success flows
do not write here — this table is for debugging, not telemetry.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class AgentErrorLog(Base, TimestampMixin):
    """A single agent failure record for debugging and support."""

    __tablename__ = "agent_error_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    conversation_id = Column(Integer, nullable=True, index=True)
    request_id = Column(String(100), nullable=True)
    # retrieve / generate / citation / save / other
    step = Column(String(50), nullable=False)
    provider = Column(String(50), nullable=True)
    model = Column(String(50), nullable=True)
    config_id = Column(Integer, nullable=True)
    error_type = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    traceback_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    # unresolved / resolved / ignored
    resolved_status = Column(String(20), default="unresolved", nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AgentErrorLog id={self.id} step={self.step!r} "
            f"error_type={self.error_type!r} user_id={self.user_id}>"
        )
