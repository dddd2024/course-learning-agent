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
from app.models import ConceptCompareReport, ConceptNode


def get_or_create_compare_report(
    db: Session,
    user_id: int,
    source_node_id: int,
    target_node_id: int,
    edge_id: int | None = None,
    user_focus: str = "concept",
) -> dict[str, Any] | None:
    """Get cached report or generate a new one.

    Returns a dict shaped for CompareReportResponse, or None if either
    node does not exist (or does not belong to the user).
    """
    n1 = db.query(ConceptNode).filter_by(
        id=source_node_id, user_id=user_id
    ).first()
    n2 = db.query(ConceptNode).filter_by(
        id=target_node_id, user_id=user_id
    ).first()
    if n1 is None or n2 is None:
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

    # Generate a fresh report via the compare agent.
    result = generate_compare(
        db,
        user_id,
        concept_a={"title": n1.title, "summary": n1.summary or ""},
        concept_b={"title": n2.title, "summary": n2.summary or ""},
        evidence_chunks=[],
        user_config=None,
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
