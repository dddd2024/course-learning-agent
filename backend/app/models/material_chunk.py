"""MaterialChunk ORM model.

A chunk is a fixed-size slice of a parsed material used for retrieval
and citation. Chunks are produced by the parse pipeline
(``POST /materials/{id}/parse``) and stored alongside the material.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text, Float

from app.models.base import Base, TimestampMixin


class MaterialChunk(Base, TimestampMixin):
    """A text chunk produced by parsing and splitting a material."""

    __tablename__ = "material_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(
        Integer, ForeignKey("materials.id"), nullable=False, index=True
    )
    material_version_id = Column(
        Integer, ForeignKey("material_versions.id"), nullable=True, index=True
    )
    stable_key = Column(String(128), nullable=True, index=True)
    content_hash = Column(String(64), nullable=True, index=True)
    is_active = Column(Integer, nullable=False, default=1)
    course_id = Column(
        Integer, ForeignKey("courses.id"), nullable=False, index=True
    )
    chunk_index = Column(Integer, nullable=False)
    title = Column(String(255))
    page_no = Column(Integer)
    text = Column(Text, nullable=False)
    raw_text = Column(Text, nullable=True)
    cleaner_version = Column(String(32), nullable=True)
    noise_score = Column(Float, nullable=True)
    is_indexable = Column(Integer, nullable=False, default=1)
    token_count = Column(Integer)
    char_count = Column(Integer, nullable=True)
    estimated_token_count = Column(Integer, nullable=True)
    keyword_text = Column(Text)  # cleaned text used for keyword retrieval
    embedding_id = Column(String(100))
    quality_score = Column(Float, nullable=True)  # AI quality score 0.0-1.0
    quality_reason = Column(String(500))  # AI quality assessment reason
    # LEARN-V3-01: JSON dict of noise types detected (line_repetition,
    # short_line_stacking, low_diversity) so the UI can show why a chunk
    # was filtered out of retrieval.
    noise_flags = Column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<MaterialChunk id={self.id} material_id={self.material_id} "
            f"chunk_index={self.chunk_index}>"
        )
