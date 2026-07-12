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
    stable_key = Column(String(320), nullable=True, index=True)
    title_normalized = Column(String(255), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="active")
    source_version_ids = Column(Text, default="[]")
    summary = Column(Text)
    importance = Column(Integer, default=3)  # 1-5
    source_chunk_ids = Column(Text)  # JSON-serialised list of chunk ids
    exam_style = Column(Text)  # likely exam format
    review_action = Column(Text)  # suggested review task
    parent_id = Column(
        Integer, ForeignKey("knowledge_points.id"), nullable=True
    )  # supports tree structure
    # V6-30: generation number for version tracking.  Each regeneration
    # creates new active KPs with an incremented generation and archives
    # the old ones.  This preserves historical quiz/evidence references
    # while keeping the active outline up to date.
    generation = Column(Integer, default=1, nullable=False, server_default="1")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<KnowledgePoint id={self.id} title={self.title!r} "
            f"course_id={self.course_id} importance={self.importance}>"
        )
