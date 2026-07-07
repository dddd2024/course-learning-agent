"""Concept graph API endpoints.

Endpoints:
- POST /concept-graph/rebuild          — sync KP -> ConceptNode, generate edges
- GET  /concept-graph                  — list user's nodes + edges (with filters)
- GET  /concept-graph/nodes/{node_id}  — node detail with related edges
- POST /concept-graph/edges/{id}/confirm — set status=confirmed
- POST /concept-graph/edges/{id}/reject  — set status=rejected
- POST /concept-graph/compare          — generate compare report (added in P5)
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import User
from app.schemas.concept_graph import (
    CompareReportResponse,
    CompareRequest,
    EdgeActionResponse,
    GraphResponse,
    NodeDetailResponse,
    RebuildResponse,
)
from app.services.concept_compare_service import get_or_create_compare_report
from app.services.concept_graph_service import (
    confirm_edge,
    generate_candidate_edges,
    get_graph,
    get_node_detail,
    reject_edge,
    sync_nodes_for_user,
)

router = APIRouter()


@router.post("/rebuild", response_model=RebuildResponse)
def rebuild_graph(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sync knowledge points into concept nodes and generate candidate edges."""
    nodes_count = sync_nodes_for_user(db, current_user.id)
    edges_count = generate_candidate_edges(db, current_user.id)
    db.commit()
    return RebuildResponse(
        nodes_count=nodes_count, edges_count=edges_count
    )


@router.get("", response_model=GraphResponse)
def get_user_graph(
    course_ids: str | None = None,
    relation_type: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the user's graph, optionally filtered by course/relation/status."""
    cids = None
    if course_ids:
        cids = [int(x) for x in course_ids.split(",") if x.strip()]
    graph = get_graph(
        db, current_user.id, course_ids=cids,
        relation_type=relation_type, status=status,
    )
    return GraphResponse(**graph)


@router.get("/nodes/{node_id}", response_model=NodeDetailResponse)
def get_node(
    node_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return node detail with related edges. 404 if not owned by user."""
    detail = get_node_detail(db, current_user.id, node_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    return NodeDetailResponse(**detail)


@router.post("/edges/{edge_id}/confirm", response_model=EdgeActionResponse)
def confirm(
    edge_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set an edge's status to 'confirmed'. 404 if not owned by user."""
    edge = confirm_edge(db, current_user.id, edge_id)
    if edge is None:
        raise HTTPException(status_code=404, detail="边不存在")
    db.commit()
    return EdgeActionResponse(**_edge_to_response_dict(edge))


@router.post("/edges/{edge_id}/reject", response_model=EdgeActionResponse)
def reject(
    edge_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set an edge's status to 'rejected'. 404 if not owned by user."""
    edge = reject_edge(db, current_user.id, edge_id)
    if edge is None:
        raise HTTPException(status_code=404, detail="边不存在")
    db.commit()
    return EdgeActionResponse(**_edge_to_response_dict(edge))


@router.post("/compare", response_model=CompareReportResponse)
def compare(
    req: CompareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate (or return cached) compare report for two nodes.

    404 if either node does not exist or belongs to another user.
    """
    result = get_or_create_compare_report(
        db, current_user.id, req.source_node_id, req.target_node_id,
        req.edge_id, req.user_focus,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    db.commit()
    return CompareReportResponse(**result)


def _edge_to_response_dict(edge) -> dict:
    return {
        "id": edge.id,
        "user_id": edge.user_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "relation_type": edge.relation_type,
        "confidence": edge.confidence,
        "reason": edge.reason or "",
        "evidence_chunk_ids": json.loads(edge.evidence_chunk_ids or "[]"),
        "status": edge.status,
        "audit_run_id": edge.audit_run_id,
    }
