"""MaterialChunk ORM model.

A chunk is a fixed-size slice of a parsed material used for retrieval
and citation. Chunks are produced by the parse pipeline
(``POST /materials/{id}/parse``) and stored alongside the material.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class MaterialChunk(Base, TimestampMixin):
    """A text chunk produced by parsing and splitting a material."""

    __tablename__ = "material_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(
        Integer, ForeignKey("materials.id"), nullable=False, index=True
    )
    course_id = Column(
        Integer, ForeignKey("courses.id"), nullable=False, index=True
    )
    chunk_index = Column(Integer, nullable=False)
    title = Column(String(255))
    page_no = Column(Integer)
    text = Column(Text, nullable=False)
    token_count = Column(Integer)
    keyword_text = Column(Text)  # cleaned text used for keyword retrieval
    embedding_id = Column(String(100))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<MaterialChunk id={self.id} material_id={self.material_id} "
            f"chunk_index={self.chunk_index}>"
        )
