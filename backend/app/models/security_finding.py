"""MaterialSecurityFinding ORM model (Phase 2 Task D).

Records chunks that contain potential prompt-injection patterns
so the frontend can surface them in the material detail page and
the RAG agent can wrap material content with a guard statement.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class MaterialSecurityFinding(Base, TimestampMixin):
    """A suspicious chunk flagged by the upload security scanner."""

    __tablename__ = "material_security_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(
        Integer, ForeignKey("materials.id"), nullable=False, index=True
    )
    chunk_id = Column(
        Integer, ForeignKey("material_chunks.id"), nullable=False
    )
    # injection / override / credential_request / role_hijack / other
    finding_type = Column(String(50), nullable=False, default="injection")
    # The matched text snippet (truncated for display)
    snippet = Column(Text)
    # Short human-readable description of why it was flagged
    note = Column(String(255))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<MaterialSecurityFinding id={self.id} "
            f"material_id={self.material_id} "
            f"finding_type={self.finding_type!r}>"
        )
