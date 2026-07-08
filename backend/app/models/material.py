"""Material ORM model."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.timezone import utc_now
from app.models.base import Base, TimestampMixin


class Material(Base, TimestampMixin):
    """A learning material file uploaded by a user for a course."""

    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)  # 扩展名 txt/pdf/docx
    file_path = Column(String(500), nullable=False)  # 存储相对路径
    status = Column(String(30), default="uploaded")  # uploaded/processing/ready/failed
    version = Column(Integer, default=1)
    error_message = Column(Text)
    # timezone-aware upload time (replaces the old naive datetime.utcnow).
    uploaded_at = Column(DateTime(timezone=True), default=utc_now)
    # Parse-task tracking for retry + timeout recovery.
    # parse_started_at: when the current/last parse attempt began (timezone-aware).
    # parse_finished_at: when the current/last parse attempt ended.
    # parse_attempts: how many tries the current parse run has used (resets on success).
    # last_parse_error: human-readable reason for the most recent failure.
    parse_started_at = Column(DateTime(timezone=True), nullable=True)
    parse_finished_at = Column(DateTime(timezone=True), nullable=True)
    parse_attempts = Column(Integer, default=0, nullable=False)
    last_parse_error = Column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Material id={self.id} filename={self.filename!r} "
            f"course_id={self.course_id} status={self.status!r}>"
        )
