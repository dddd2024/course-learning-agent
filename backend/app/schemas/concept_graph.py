"""Pydantic schemas for concept graph API."""
from typing import Literal

from pydantic import BaseModel


class GraphNode(BaseModel):
    id: int
    user_id: int
    course_id: int
    knowledge_point_id: int | None = None
    title: str
    normalized_title: str
    summary: str = ""
    aliases: list[str] = []
    importance: int = 3
    source_chunk_ids: list[int] = []
    weak_point_score: float = 0.0


class GraphEdge(BaseModel):
    id: int
    user_id: int
    source_node_id: int
    target_node_id: int
    relation_type: str
    confidence: float
    reason: str = ""
    evidence_chunk_ids: list[int] = []
    status: str = "candidate"
    audit_run_id: int | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class RebuildResponse(BaseModel):
    nodes_count: int
    edges_count: int


class NodeDetailResponse(GraphNode):
    related_edges: list[GraphEdge] = []


class EdgeActionResponse(GraphEdge):
    pass


class CompareRequest(BaseModel):
    source_node_id: int
    target_node_id: int
    edge_id: int | None = None
    user_focus: Literal["concept", "exam", "transfer"] = "concept"


class CompareReportResponse(BaseModel):
    id: int
    source_node_id: int
    target_node_id: int
    edge_id: int | None = None
    report_json: dict
    citation_chunk_ids: list[int] = []
    prompt_version: str = "v1"
    provider: str = "mock"
    model_name: str = "mock"
    fallback_used: bool = False
    fallback_reason: str = ""
    audit_run_id: int | None = None
