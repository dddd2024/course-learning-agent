"""KnowledgePoint ORM model.

A knowledge point is a structured concept extracted from a course's
materials by the ``OutlineAgent``. Each point carries a summary,
importance (1-5), the chunks it was derived from, an exam-style hint,
and a suggested review action. ``parent_id`` allows points to form a
tree (course -> chapter -> section -> point) for future use.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class KnowledgePoint(Base, TimestampMixin):
    """A single knowledge point extracted from a course's materials."""

    __tablename__ = "knowledge_points"

    id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(
        Integer, ForeignKey("courses.id"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    title = Column(String(255), nullable=False)
    summary = Column(Text)
    importance = Column(Integer, default=3)  # 1-5
    source_chunk_ids = Column(Text)  # JSON-serialised list of chunk ids
    exam_style = Column(Text)  # likely exam format
    review_action = Column(Text)  # suggested review task
    parent_id = Column(
        Integer, ForeignKey("knowledge_points.id"), nullable=True
    )  # supports tree structure

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<KnowledgePoint id={self.id} title={self.title!r} "
            f"course_id={self.course_id} importance={self.importance}>"
        )
