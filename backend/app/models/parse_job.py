"""Durable material parsing jobs.

The row is intentionally separate from ``Material.status``: status is the
user-facing material state while a job keeps retry/heartbeat/error history
across process restarts.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class ParseJob(Base, TimestampMixin):
    __tablename__ = "parse_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True)
    material_version_id = Column(Integer, ForeignKey("material_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)
    attempt = Column(Integer, nullable=False, default=0)
    heartbeat_at = Column(DateTime, nullable=True, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    cancellation_reason = Column(Text, nullable=True)
