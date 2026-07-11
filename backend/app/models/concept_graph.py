"""Cross-course concept graph models.

ConceptNode  — a knowledge point synced into the graph layer.
ConceptEdge  — a discovered relationship between two nodes.
ConceptCompareReport — cached structured compare report.
"""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class ConceptNode(Base, TimestampMixin):
    """A knowledge point synced into the cross-course graph layer."""

    __tablename__ = "concept_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    course_id = Column(
        Integer, ForeignKey("courses.id"), nullable=False, index=True
    )
    knowledge_point_id = Column(
        Integer, ForeignKey("knowledge_points.id"), nullable=True
    )
    title = Column(String(255), nullable=False)
    normalized_title = Column(String(255), nullable=False, index=True)
    summary = Column(Text, default="")
    aliases = Column(Text, default="[]")  # JSON list
    importance = Column(Integer, default=3)  # 1-5
    source_chunk_ids = Column(Text, default="[]")  # JSON list
    weak_point_score = Column(Float, default=0.0)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ConceptNode id={self.id} title={self.title!r} "
            f"course_id={self.course_id}>"
        )


class ConceptEdge(Base, TimestampMixin):
    """A discovered relationship between two ConceptNodes."""

    __tablename__ = "concept_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    source_node_id = Column(
        Integer, ForeignKey("concept_nodes.id"), nullable=False, index=True
    )
    target_node_id = Column(
        Integer, ForeignKey("concept_nodes.id"), nullable=False, index=True
    )
    relation_type = Column(String(50), nullable=False)
    confidence = Column(Float, default=0.0)
    reason = Column(Text, default="")
    evidence_chunk_ids = Column(Text, default="[]")  # JSON list
    status = Column(String(20), default="candidate")  # candidate/confirmed/rejected
    audit_run_id = Column(
        Integer, ForeignKey("agent_runs.id"), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ConceptEdge id={self.id} type={self.relation_type!r} "
            f"status={self.status!r}>"
        )


class ConceptCompareReport(Base, TimestampMixin):
    """Cached structured compare report between two ConceptNodes."""

    __tablename__ = "concept_compare_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    source_node_id = Column(
        Integer, ForeignKey("concept_nodes.id"), nullable=False
    )
    target_node_id = Column(
        Integer, ForeignKey("concept_nodes.id"), nullable=False
    )
    edge_id = Column(
        Integer, ForeignKey("concept_edges.id"), nullable=True
    )
    report_json = Column(Text, default="{}")  # JSON
    citation_chunk_ids = Column(Text, default="[]")  # JSON list
    prompt_version = Column(String(50), default="v1")
    provider = Column(String(50), default="mock")
    model_name = Column(String(50), default="mock")
    user_focus = Column(String(50), default="concept", nullable=False, index=True)
    evidence_hash = Column(String(64), default="", nullable=False, index=True)
    config_id = Column(
        Integer, ForeignKey("user_llm_configs.id"), nullable=True
    )
    audit_run_id = Column(
        Integer, ForeignKey("agent_runs.id"), nullable=True
    )
    # GRAPH-V3-01: preserve compare cache generation semantics so a
    # cache hit restores the real metadata (fallback, provider, etc.)
    # instead of defaulting to fallback=false.
    report_status = Column(
        String(40), default="success", nullable=False
    )  # success / degraded / insufficient_evidence
    fallback_used = Column(Integer, default=0, nullable=False)
    fallback_reason = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    generated_at = Column(DateTime, nullable=True)
    actual_provider = Column(String(50), nullable=True)
    actual_model = Column(String(100), nullable=True)
    generation_mode = Column(
        String(20), default="real", nullable=False
    )  # real / mock / fallback

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ConceptCompareReport id={self.id}>"
