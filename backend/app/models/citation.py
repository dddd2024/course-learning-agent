"""Citation ORM model.

A citation is a reference from an assistant message to a specific
material chunk. It is persisted after every chat answer so the
frontend can re-fetch the supporting evidence for any message without
replaying the retrieval/agent pipeline.
"""
from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class Citation(Base, TimestampMixin):
    """A single citation linking an assistant message to a chunk."""

    __tablename__ = "citations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(
        Integer, ForeignKey("messages.id"), nullable=False, index=True
    )
    chunk_id = Column(
        Integer, ForeignKey("material_chunks.id"), nullable=False
    )
    quote_text = Column(Text)
    claim_text = Column(Text)
    support_status = Column(String(20), nullable=False, default="weak")
    verification_reason = Column(Text)
    verifier_version = Column(String(30))
    confidence = Column(Float, default=0.0)
    page_no = Column(Integer)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Citation id={self.id} message_id={self.message_id} "
            f"chunk_id={self.chunk_id}>"
        )
