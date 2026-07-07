"""Concept graph service: node sync, candidate edge generation, graph query.

Candidate edges use rule-based matching (no LLM) in this module:
- same_name_different_meaning: identical normalized title, different course, low summary overlap
- similar_to: same title + high summary overlap, or keyword overlap
- applies_to: cross-course similar_to
- prerequisite_of: one summary mentions the other's title
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    ConceptEdge,
    ConceptNode,
    KnowledgePoint,
    WeakPoint,
)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _normalize_title(title: str) -> str:
    """Lowercase, strip, collapse whitespace, remove punctuation."""
    t = (title or "").lower().strip()
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _keyword_set(summary: str) -> set[str]:
    """Extract meaningful keywords from a summary.

    For Chinese text, each CJK char is a token (bigrams are too aggressive
    for short summaries). For ASCII, tokens of length >= 2.
    """
    if not summary:
        return set()
    # CJK chars individually + ASCII words of length >= 2
    cjk = re.findall(r"[\u4e00-\u9fff]", summary)
    ascii_words = re.findall(r"[a-zA-Z]{2,}", summary)
    return set(cjk) | set(w.lower() for w in ascii_words)


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _load_json_ids(value: str | None) -> list[int]:
    """Parse a JSON string of int ids, tolerating bad input."""
    try:
        raw = json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    ids = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    return ids


def _merge_evidence_ids(a: ConceptNode, b: ConceptNode) -> list[int]:
    """Merge source_chunk_ids from two nodes, de-duplicating."""
    seen: set[int] = set()
    merged: list[int] = []
    for cid in _load_json_ids(a.source_chunk_ids) + _load_json_ids(
        b.source_chunk_ids
    ):
        if cid not in seen:
            seen.add(cid)
            merged.append(cid)
    return merged


# ---------------------------------------------------------------------------
# Node sync
# ---------------------------------------------------------------------------


def sync_nodes_for_user(db: Session, user_id: int) -> int:
    """Sync KnowledgePoint -> ConceptNode for all of a user's courses.

    Idempotent: existing nodes (matched by course_id + knowledge_point_id)
    are updated in place, not duplicated. Returns the number of nodes.
    """
    kps = db.query(KnowledgePoint).filter_by(user_id=user_id).all()
    existing: dict[tuple[int, int], ConceptNode] = {
        (n.course_id, n.knowledge_point_id): n
        for n in db.query(ConceptNode).filter_by(user_id=user_id).all()
    }
    weak_rows = db.query(WeakPoint).filter_by(user_id=user_id).all()
    weak_kp_ids = {w.knowledge_point_id for w in weak_rows}

    count = 0
    for kp in kps:
        key = (kp.course_id, kp.id)
        node = existing.get(key)
        norm = _normalize_title(kp.title or "")
        if node is None:
            node = ConceptNode(
                user_id=user_id,
                course_id=kp.course_id,
                knowledge_point_id=kp.id,
                title=kp.title or "",
                normalized_title=norm,
                summary=kp.summary or "",
                aliases="[]",
                importance=kp.importance or 3,
                source_chunk_ids=kp.source_chunk_ids or "[]",
                weak_point_score=1.0 if kp.id in weak_kp_ids else 0.0,
            )
            db.add(node)
        else:
            node.title = kp.title or ""
            node.normalized_title = norm
            node.summary = kp.summary or ""
            node.importance = kp.importance or 3
            node.source_chunk_ids = kp.source_chunk_ids or "[]"
            node.weak_point_score = 1.0 if kp.id in weak_kp_ids else 0.0
        count += 1
    db.flush()
    return count


# ---------------------------------------------------------------------------
# Candidate edge generation
# ---------------------------------------------------------------------------


def generate_candidate_edges(db: Session, user_id: int) -> int:
    """Generate candidate edges using rule-based matching.

    Skips pairs that already have a confirmed/rejected edge.
    Skips pairs that already have a candidate edge (no duplicates).
    Returns the number of new edges created.
    """
    nodes = db.query(ConceptNode).filter_by(user_id=user_id).all()
    if len(nodes) < 2:
        return 0

    # existing[(min_id, max_id)] = set of statuses
    existing: dict[tuple[int, int], set[str]] = defaultdict(set)
    for e in db.query(ConceptEdge).filter_by(user_id=user_id).all():
        key = (
            min(e.source_node_id, e.target_node_id),
            max(e.source_node_id, e.target_node_id),
        )
        existing[key].add(e.status)

    created = 0
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            key = (min(a.id, b.id), max(a.id, b.id))
            statuses = existing[key]
            if "confirmed" in statuses or "rejected" in statuses:
                continue
            if "candidate" in statuses:
                continue

            edge = _try_make_edge(a, b)
            if edge is not None:
                edge.user_id = user_id
                db.add(edge)
                created += 1
    db.flush()
    return created


def _try_make_edge(a: ConceptNode, b: ConceptNode) -> ConceptEdge | None:
    """Apply rules to decide if a-b should have an edge. Returns edge or None."""
    same_title = (
        a.normalized_title == b.normalized_title
        and a.normalized_title != ""
    )
    diff_course = a.course_id != b.course_id
    kw_a = _keyword_set(a.summary or "")
    kw_b = _keyword_set(b.summary or "")
    kw_overlap = _jaccard(kw_a, kw_b)
    title_in_summary = (
        (a.title and a.title in (b.summary or ""))
        or (b.title and b.title in (a.summary or ""))
    )

    evidence_ids = _merge_evidence_ids(a, b)
    evidence_json = json.dumps(evidence_ids)
    no_evidence_suffix = (
        "（缺少来源 chunk，仅基于知识点摘要生成）"
        if not evidence_ids
        else ""
    )

    # Rule 1: same normalized title, different course
    if same_title and diff_course:
        if kw_overlap < 0.6:
            return ConceptEdge(
                source_node_id=a.id,
                target_node_id=b.id,
                relation_type="same_name_different_meaning",
                confidence=0.7,
                reason=f"同名概念「{a.title}」在两门课中含义不同{no_evidence_suffix}",
                evidence_chunk_ids=evidence_json,
                status="candidate",
            )
        else:
            return ConceptEdge(
                source_node_id=a.id,
                target_node_id=b.id,
                relation_type="similar_to",
                confidence=0.8,
                reason=f"同名概念「{a.title}」在两门课中含义相近{no_evidence_suffix}",
                evidence_chunk_ids=evidence_json,
                status="candidate",
            )

    # Rule 2: keyword overlap -> similar_to / applies_to
    if kw_overlap >= 0.2:
        rtype = "applies_to" if diff_course else "similar_to"
        return ConceptEdge(
            source_node_id=a.id,
            target_node_id=b.id,
            relation_type=rtype,
            confidence=0.45 + 0.3 * kw_overlap,
            reason=f"摘要关键词重叠度 {kw_overlap:.2f}{no_evidence_suffix}",
            evidence_chunk_ids=evidence_json,
            status="candidate",
        )

    # Rule 3: one summary mentions the other's title
    if title_in_summary:
        return ConceptEdge(
            source_node_id=a.id,
            target_node_id=b.id,
            relation_type="prerequisite_of",
            confidence=0.6,
            reason=f"一方摘要提及另一方标题{no_evidence_suffix}",
            evidence_chunk_ids=evidence_json,
            status="candidate",
        )

    return None


# ---------------------------------------------------------------------------
# Graph query
# ---------------------------------------------------------------------------


def get_graph(
    db: Session,
    user_id: int,
    course_ids: list[int] | None = None,
    relation_type: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Return {nodes: [...], edges: [...]} for the user."""
    node_q = db.query(ConceptNode).filter_by(user_id=user_id)
    if course_ids:
        node_q = node_q.filter(ConceptNode.course_id.in_(course_ids))
    nodes = node_q.all()
    node_ids = {n.id for n in nodes}

    edge_q = db.query(ConceptEdge).filter_by(user_id=user_id)
    if relation_type:
        edge_q = edge_q.filter(ConceptEdge.relation_type == relation_type)
    if status:
        edge_q = edge_q.filter(ConceptEdge.status == status)
    edges = [
        e for e in edge_q.all()
        if e.source_node_id in node_ids and e.target_node_id in node_ids
    ]

    return {
        "nodes": [_node_to_dict(n) for n in nodes],
        "edges": [_edge_to_dict(e) for e in edges],
    }


def get_node_detail(
    db: Session, user_id: int, node_id: int
) -> dict[str, Any] | None:
    """Return node dict with related_edges, or None if not found."""
    node = db.query(ConceptNode).filter_by(
        id=node_id, user_id=user_id
    ).first()
    if node is None:
        return None
    node_dict = _node_to_dict(node)
    edges = (
        db.query(ConceptEdge)
        .filter_by(user_id=user_id)
        .filter(
            (ConceptEdge.source_node_id == node_id)
            | (ConceptEdge.target_node_id == node_id)
        )
        .all()
    )
    node_dict["related_edges"] = [_edge_to_dict(e) for e in edges]
    return node_dict


# ---------------------------------------------------------------------------
# Edge status actions
# ---------------------------------------------------------------------------


def confirm_edge(
    db: Session, user_id: int, edge_id: int
) -> ConceptEdge | None:
    """Set edge status to 'confirmed'. Returns edge or None if not found."""
    edge = db.query(ConceptEdge).filter_by(
        id=edge_id, user_id=user_id
    ).first()
    if edge is None:
        return None
    edge.status = "confirmed"
    db.flush()
    return edge


def reject_edge(
    db: Session, user_id: int, edge_id: int
) -> ConceptEdge | None:
    """Set edge status to 'rejected'. Returns edge or None if not found."""
    edge = db.query(ConceptEdge).filter_by(
        id=edge_id, user_id=user_id
    ).first()
    if edge is None:
        return None
    edge.status = "rejected"
    db.flush()
    return edge


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _node_to_dict(n: ConceptNode) -> dict[str, Any]:
    return {
        "id": n.id,
        "user_id": n.user_id,
        "course_id": n.course_id,
        "knowledge_point_id": n.knowledge_point_id,
        "title": n.title,
        "normalized_title": n.normalized_title,
        "summary": n.summary or "",
        "aliases": json.loads(n.aliases or "[]"),
        "importance": n.importance,
        "source_chunk_ids": json.loads(n.source_chunk_ids or "[]"),
        "weak_point_score": n.weak_point_score,
    }


def _edge_to_dict(e: ConceptEdge) -> dict[str, Any]:
    return {
        "id": e.id,
        "user_id": e.user_id,
        "source_node_id": e.source_node_id,
        "target_node_id": e.target_node_id,
        "relation_type": e.relation_type,
        "confidence": e.confidence,
        "reason": e.reason or "",
        "evidence_chunk_ids": json.loads(e.evidence_chunk_ids or "[]"),
        "status": e.status,
        "audit_run_id": e.audit_run_id,
    }
