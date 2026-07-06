"""Material ORM model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

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
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Material id={self.id} filename={self.filename!r} "
            f"course_id={self.course_id} status={self.status!r}>"
        )
