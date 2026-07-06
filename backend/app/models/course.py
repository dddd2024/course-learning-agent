"""Course ORM model."""
from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class Course(Base, TimestampMixin):
    """A course owned by a user."""

    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    teacher = Column(String(100))
    semester = Column(String(50))
    description = Column(Text)
    color = Column(String(20))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Course id={self.id} name={self.name!r} user_id={self.user_id}>"
