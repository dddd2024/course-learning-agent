"""Concept compare service: caching + orchestration.

Looks up an existing ConceptCompareReport for the (source, target) pair
(in either order) before calling the compare agent. Persists new reports
and returns a dict shaped for the CompareReportResponse schema.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.agents.concept_compare import generate_compare
from app.core.exceptions import BusinessException
from app.models import (
    ConceptCompareReport,
    ConceptEdge,
    ConceptNode,
    Course,
    MaterialChunk,
)


def build_compare_cache_key(*, provider: str, model: str, generation_mode: str, prompt_version: str, evidence_hash: str) -> dict[str, str]:
    return {"provider": provider, "model_name": model, "generation_mode": generation_mode, "prompt_version": prompt_version, "evidence_hash": evidence_hash}


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


def _compute_evidence_hash(evidence_chunks: list[dict]) -> str:
    """SHA1 of evidence content (chunk_id + material_id + course_id + page_no + title + text), truncated to 16 chars.

    基于内容而非仅 chunk_id，保证同 chunk_id 文本变化时缓存失效。
    """
    if not evidence_chunks:
        return ""
    parts: list[str] = []
    for c in sorted(evidence_chunks, key=lambda x: x.get("chunk_id", 0)):
        parts.append(
            f"{c.get('chunk_id', '')}|{c.get('material_id', '')}|"
            f"{c.get('course_id', '')}|{c.get('page_no', '')}|"
            f"{c.get('title', '')}|{c.get('text', '')}"
        )
    payload = "\n".join(parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def get_or_create_compare_report(
    db: Session,
    user_id: int,
    source_node_id: int,
    target_node_id: int,
    edge_id: int | None = None,
    user_focus: str = "concept",
    user_config: dict | None = None,
    force_refresh: bool = False,
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
            raise BusinessException(
                message="edge 与请求的节点对不匹配"
            )

    # Collect evidence chunk ids, load their content, then compute a
    # content-aware hash so cache invalidates when text changes (not just
    # when chunk ids change).
    chunk_ids = _collect_chunk_ids(n1, n2, edge)
    evidence_chunks = _load_evidence_chunks(db, user_id, chunk_ids)
    evidence_hash = _compute_evidence_hash(evidence_chunks)

    # A summary or title is not source evidence.  Persist a clearly marked
    # non-report so the UI can explain the remediation without fabricating
    # similarities, differences, transfer advice, or exam claims.
    if not evidence_chunks:
        cached = db.query(ConceptCompareReport).filter_by(
            user_id=user_id, source_node_id=source_node_id,
            target_node_id=target_node_id, user_focus=user_focus,
            evidence_hash="",
        ).first() or db.query(ConceptCompareReport).filter_by(
            user_id=user_id, source_node_id=target_node_id,
            target_node_id=source_node_id, user_focus=user_focus,
            evidence_hash="",
        ).first()
        if cached is not None and not force_refresh:
            return _report_to_dict(cached)
        report = ConceptCompareReport(
            user_id=user_id, source_node_id=source_node_id,
            target_node_id=target_node_id, edge_id=edge_id,
            report_json=json.dumps({
                "status": "insufficient_evidence",
                "reason": "两个概念都缺少可访问的原始资料片段。",
                "required_sources": ["已解析且仍可访问的资料原文"],
                "next_action": "请重新解析资料并重建知识点后再生成对比。",
                "concept_a": {"title": n1.title}, "concept_b": {"title": n2.title},
                "similarities": [], "differences": [], "transfer_learning": [],
                "confusions": [], "exam_questions": [],
            }, ensure_ascii=False),
            citation_chunk_ids="[]", prompt_version="v1", provider="mock",
            model_name="mock", user_focus=user_focus, evidence_hash="",
            report_status="insufficient_evidence",
            fallback_used=0,
            generation_mode="mock",
        )
        db.add(report)
        db.flush()
        return _report_to_dict(report)

    # Cache lookup: same user + same node pair (either order)
    # + same user_focus + same evidence_hash + same prompt_version.
    # GRAPH-V3-01: also match on provider so a report generated with
    # mock mode is NOT served when a real model is now available.
    # When force_refresh: do NOT return old degraded reports.
    desired_provider = (user_config or {}).get("provider") or "mock"
    desired_model = (user_config or {}).get("model") or "mock"
    desired_mode = "real" if user_config else "mock"
    key = build_compare_cache_key(provider=desired_provider, model=desired_model, generation_mode=desired_mode, prompt_version="v1", evidence_hash=evidence_hash)
    cached = db.query(ConceptCompareReport).filter_by(
        user_id=user_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        user_focus=user_focus,
        **key,
    ).first()
    if cached is None:
        cached = db.query(ConceptCompareReport).filter_by(
            user_id=user_id,
            source_node_id=target_node_id,
            target_node_id=source_node_id,
            user_focus=user_focus,
            **key,
        ).first()
    if (
        cached is not None
        and not force_refresh
        and (cached.expires_at is None or cached.expires_at > datetime.now())
        and (cached.report_status or "success") not in
            ("degraded", "insufficient_evidence")
    ):
        return _report_to_dict(cached)

    # Generate a fresh report via the compare agent.
    result = generate_compare(
        db,
        user_id,
        concept_a={"title": n1.title, "summary": n1.summary or ""},
        concept_b={"title": n2.title, "summary": n2.summary or ""},
        evidence_chunks=evidence_chunks,
        user_config=user_config,
        user_focus=user_focus,
    )

    from app.core.timezone import utc_now

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
        user_focus=user_focus,
        evidence_hash=evidence_hash,
        audit_run_id=result["audit_run_id"],
        # GRAPH-V3-01: persist complete generation metadata so a cache
        # hit restores the real fallback/provider/model state.
        report_status=result.get("report_status", "success"),
        fallback_used=1 if result.get("fallback_used") else 0,
        fallback_reason=result.get("fallback_reason") or None,
        generated_at=utc_now(),
        actual_provider=result.get("provider"),
        actual_model=result.get("model_name"),
        generation_mode=result.get("generation_mode", "real"),
        expires_at=utc_now() + timedelta(hours=24),
    )
    db.add(report)
    db.flush()
    return _report_to_dict(report, result)


def _report_to_dict(
    report: ConceptCompareReport, gen_meta: dict | None = None
) -> dict[str, Any]:
    """Build the response dict from a ConceptCompareReport row.

    When ``gen_meta`` is provided (fresh generation), it takes precedence
    over the DB-stored columns so the just-computed values are returned.
    When ``gen_meta`` is None (cache hit), all metadata is restored from
    the DB row so a cached degraded report keeps its real fallback_used /
    report_status instead of defaulting to fallback=false.
    """
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
        "fallback_used": bool(
            meta.get(
                "fallback_used",
                bool(report.fallback_used) if report.fallback_used is not None else False,
            )
        ),
        "fallback_reason": meta.get(
            "fallback_reason",
            report.fallback_reason or "",
        ),
        "audit_run_id": report.audit_run_id,
        "report_status": meta.get(
            "report_status",
            report.report_status or "success",
        ),
        "expires_at": getattr(report, "expires_at", None),
        "generated_at": getattr(report, "generated_at", None),
        "actual_provider": meta.get(
            "actual_provider",
            getattr(report, "actual_provider", None) or report.provider,
        ),
        "actual_model": meta.get(
            "actual_model",
            getattr(report, "actual_model", None) or report.model_name,
        ),
        "generation_mode": meta.get(
            "generation_mode",
            getattr(report, "generation_mode", None) or "real",
        ),
    }


__all__ = ["get_or_create_compare_report"]
