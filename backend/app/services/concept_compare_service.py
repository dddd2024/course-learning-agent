"""Concept compare service: caching + orchestration.

Looks up an existing ConceptCompareReport for the (source, target) pair
(in either order) before calling the compare agent. Persists new reports
and returns a dict shaped for the CompareReportResponse schema.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.concept_compare import generate_compare
from app.models import (
    ConceptCompareReport,
    ConceptEdge,
    ConceptNode,
    Course,
    MaterialChunk,
)


def _load_evidence_chunks(
    db: Session, user_id: int, chunk_ids: list[int]
) -> list[dict]:
    """Load MaterialChunk rows owned by the user, returning dicts for the agent."""
    if not chunk_ids:
        return []
    rows = (
        db.query(MaterialChunk)
        .join(Course, Course.id == MaterialChunk.course_id)
        .filter(Course.user_id == user_id)
        .filter(MaterialChunk.id.in_(chunk_ids))
        .all()
    )
    return [
        {
            "chunk_id": r.id,
            "course_id": r.course_id,
            "material_id": r.material_id,
            "title": r.title or "",
            "page_no": r.page_no,
            "text": (r.text or "")[:1200],
        }
        for r in rows
    ]


def _collect_chunk_ids(
    n1: ConceptNode, n2: ConceptNode, edge: ConceptEdge | None
) -> list[int]:
    """Collect candidate chunk ids from both nodes and the edge."""
    ids: list[int] = []
    for raw in (n1.source_chunk_ids, n2.source_chunk_ids):
        try:
            ids.extend(int(x) for x in json.loads(raw or "[]"))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    if edge is not None:
        try:
            ids.extend(
                int(x)
                for x in json.loads(edge.evidence_chunk_ids or "[]")
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    seen: set[int] = set()
    unique: list[int] = []
    for cid in ids:
        if cid not in seen:
            seen.add(cid)
            unique.append(cid)
    return unique


def get_or_create_compare_report(
    db: Session,
    user_id: int,
    source_node_id: int,
    target_node_id: int,
    edge_id: int | None = None,
    user_focus: str = "concept",
    user_config: dict | None = None,
) -> dict[str, Any] | None:
    """Get cached report or generate a new one.

    Returns a dict shaped for CompareReportResponse, or None if either
    node does not exist (or does not belong to the user), or if edge_id
    is provided but doesn't belong to the user or doesn't connect the
    same node pair.
    """
    n1 = db.query(ConceptNode).filter_by(
        id=source_node_id, user_id=user_id
    ).first()
    n2 = db.query(ConceptNode).filter_by(
        id=target_node_id, user_id=user_id
    ).first()
    if n1 is None or n2 is None:
        return None

    # edge_id ownership and consistency validation
    edge = None
    if edge_id is not None:
        edge = db.query(ConceptEdge).filter_by(
            id=edge_id, user_id=user_id
        ).first()
        if edge is None:
            return None
        edge_pair = {edge.source_node_id, edge.target_node_id}
        req_pair = {source_node_id, target_node_id}
        if edge_pair != req_pair:
            return None

    # Cache lookup: same user + same node pair in either order.
    cached = db.query(ConceptCompareReport).filter_by(
        user_id=user_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
    ).first()
    if cached is None:
        cached = db.query(ConceptCompareReport).filter_by(
            user_id=user_id,
            source_node_id=target_node_id,
            target_node_id=source_node_id,
        ).first()
    if cached is not None:
        return _report_to_dict(cached)

    # Collect evidence chunks from nodes and edge.
    chunk_ids = _collect_chunk_ids(n1, n2, edge)
    evidence_chunks = _load_evidence_chunks(db, user_id, chunk_ids)

    # Generate a fresh report via the compare agent.
    result = generate_compare(
        db,
        user_id,
        concept_a={"title": n1.title, "summary": n1.summary or ""},
        concept_b={"title": n2.title, "summary": n2.summary or ""},
        evidence_chunks=evidence_chunks,
        user_config=user_config,
    )

    report = ConceptCompareReport(
        user_id=user_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_id=edge_id,
        report_json=json.dumps(
            result["report_json"], ensure_ascii=False
        ),
        citation_chunk_ids=json.dumps(result["citation_chunk_ids"]),
        prompt_version="v1",
        provider=result["provider"],
        model_name=result["model_name"],
        audit_run_id=result["audit_run_id"],
    )
    db.add(report)
    db.flush()
    return _report_to_dict(report, result)


def _report_to_dict(
    report: ConceptCompareReport, gen_meta: dict | None = None
) -> dict[str, Any]:
    meta = gen_meta or {}
    return {
        "id": report.id,
        "source_node_id": report.source_node_id,
        "target_node_id": report.target_node_id,
        "edge_id": report.edge_id,
        "report_json": json.loads(report.report_json or "{}"),
        "citation_chunk_ids": json.loads(
            report.citation_chunk_ids or "[]"
        ),
        "prompt_version": report.prompt_version,
        "provider": report.provider,
        "model_name": report.model_name,
        "fallback_used": bool(meta.get("fallback_used", False)),
        "fallback_reason": meta.get("fallback_reason", ""),
        "audit_run_id": report.audit_run_id,
    }


__all__ = ["get_or_create_compare_report"]
