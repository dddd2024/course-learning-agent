"""Deterministic, persisted target selection for executable study tasks."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material
from app.models.material_chunk import MaterialChunk


# Concept aliases are deliberately vocabulary, not filename mappings.  The
# same normalization is applied to task titles, filenames and parsed content.
_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "overview": ("概述", "总览", "导论", "简介", "体系结构", "osi", "overview", "introduction", "architecture"),
    "physical_layer": ("物理层", "physical layer", "signal", "encoding", "传输介质"),
    "data_link_layer": ("数据链路层", "链路层", "data link layer", "mac", "frame", "帧", "差错控制"),
    "network_layer": ("网络层", "network layer", "ip协议", "ip protocol", "routing", "路由", "subnet", "子网"),
    "transport_layer": ("传输层", "transport layer", "tcp", "udp", "拥塞控制", "reliable transport"),
    "application_layer": ("应用层", "application layer", "http", "dns", "ftp"),
    "lan": ("局域网", "lan", "local area network", "ethernet", "以太网"),
    "network_security": ("网络安全", "network security", "security", "防火墙", "firewall", "认证", "加密"),
}


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (value or "").lower())


def _concepts(value: str) -> set[str]:
    compact = _compact(value)
    return {
        name
        for name, aliases in _CONCEPT_ALIASES.items()
        if any(_compact(alias) in compact for alias in aliases)
    }


def _tokens(value: str) -> set[str]:
    text = value or ""
    tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9_]+", text)}
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    # Chinese has no word separators; overlapping n-grams make “进程同步与
    # 信号量” and “信号量机制” share a meaningful, explainable signal.
    tokens.update(cjk[i:i + width] for width in (2, 3, 4) for i in range(max(0, len(cjk) - width + 1)))
    return {token for token in tokens if token}


def _choose(rows: list[Any], title: str, used_ids: set[int]) -> Any | None:
    if not rows:
        return None
    wanted = _tokens(title)
    ranked = sorted(
        rows,
        key=lambda row: (
            -(len(wanted & _tokens(getattr(row, "title", "") or getattr(row, "filename", "")))),
            row.id in used_ids,
            row.id,
        ),
    )
    candidate = ranked[0]
    candidate_tokens = _tokens(getattr(candidate, "title", "") or getattr(candidate, "filename", ""))
    # A generic plan step can truthfully resolve to the only available
    # course resource: there is no competing target to guess between.  With
    # two or more candidates, however, keep the strict overlap requirement
    # rather than silently selecting the first row.
    if wanted and not (wanted & candidate_tokens) and len(rows) != 1:
        return None
    return candidate


def _material_resolution(
    db: Session, course_id: int, title: str, used_ids: set[int]
) -> tuple[Material | None, list[dict[str, Any]]]:
    """Rank ready, versioned course materials using names and parsed content."""
    rows = (
        db.query(Material)
        .filter(
            Material.course_id == course_id,
            Material.status == "ready",
        )
        .order_by(Material.id.asc())
        .all()
    )
    if not rows:
        return None, []

    chunks_by_material: dict[int, list[MaterialChunk]] = defaultdict(list)
    active_versions = {row.id: row.active_version_id for row in rows}
    chunks = (
        db.query(MaterialChunk)
        .filter(
            MaterialChunk.material_id.in_(active_versions),
            MaterialChunk.is_active == 1,
        )
        .order_by(MaterialChunk.material_id.asc(), MaterialChunk.chunk_index.asc())
        .all()
    )
    for chunk in chunks:
        if (
            chunk.material_version_id == active_versions.get(chunk.material_id)
            and len(chunks_by_material[chunk.material_id]) < 40
        ):
            chunks_by_material[chunk.material_id].append(chunk)

    wanted_tokens = _tokens(title)
    wanted_concepts = _concepts(title)
    ranked: list[dict[str, Any]] = []
    for material in rows:
        filename = material.filename or ""
        material_chunks = chunks_by_material[material.id]
        chunk_titles = " ".join(chunk.title or "" for chunk in material_chunks)
        chunk_keywords = " ".join((chunk.keyword_text or "")[:800] for chunk in material_chunks)
        chunk_text = " ".join((chunk.text or "")[:500] for chunk in material_chunks)

        filename_overlap = wanted_tokens & _tokens(filename)
        title_overlap = wanted_tokens & _tokens(chunk_titles)
        content_overlap = wanted_tokens & _tokens(f"{chunk_keywords} {chunk_text}")
        score = len(filename_overlap) * 5 + len(title_overlap) * 3 + min(6, len(content_overlap))
        reasons: list[str] = []
        if filename_overlap:
            reasons.append("文件名关键词：" + ", ".join(sorted(filename_overlap)[:6]))
        if title_overlap:
            reasons.append("章节标题关键词：" + ", ".join(sorted(title_overlap)[:6]))

        filename_concepts = _concepts(filename)
        heading_concepts = _concepts(chunk_titles)
        content_concepts = _concepts(f"{chunk_keywords} {chunk_text}")
        for concept in sorted(wanted_concepts):
            if concept in filename_concepts:
                score += 20
                reasons.append(f"文件名概念：{concept}")
            elif concept in heading_concepts:
                score += 12
                reasons.append(f"章节标题概念：{concept}")
            elif concept in content_concepts:
                score += 5
                reasons.append(f"正文概念：{concept}")
        if material.id in used_ids:
            score -= 1
            reasons.append("该资料已被同计划其他任务使用")
        ranked.append({
            "material_id": material.id,
            "material_public_id": material.public_id,
            "filename": material.filename,
            "material_version_id": material.active_version_id,
            "score": score,
            "reasons": reasons or ["未发现可靠语义信号"],
            "_row": material,
        })

    ranked.sort(key=lambda item: (-item["score"], item["material_id"]))
    public_candidates = [{k: v for k, v in item.items() if k != "_row"} for item in ranked]
    if len(ranked) == 1:
        public_candidates[0]["reasons"] = public_candidates[0]["reasons"] + ["课程仅有一份可用资料"]
        return ranked[0]["_row"], public_candidates

    best, second = ranked[0], ranked[1]
    # A multi-material course needs a meaningful signal and a unique margin.
    if best["score"] >= 8 and best["score"] - second["score"] >= 3:
        return best["_row"], public_candidates
    return None, public_candidates


def resolve_target(
    db: Session, course_id: int, task_type: str, title: str, used_ids: set[int] | None = None
) -> tuple[str, int | None, dict[str, Any]]:
    """Return a stable target type/id plus a complete persisted target spec."""
    used_ids = used_ids or set()
    if task_type == "learn":
        material, candidates = _material_resolution(db, course_id, title, used_ids)
        if material is None:
            return "material", None, {
                "material_id": None,
                "resolution_status": "unresolved",
                "completion_mode": "loaded_and_confirmed",
                "remediation": "无法自动确定学习资料，请选择本任务要使用的资料",
                "candidates": candidates,
            }
        selected = next((item for item in candidates if item["material_id"] == material.id), None)
        return "material", material.id, {
            "material_id": material.id,
            "material_public_id": material.public_id,
            "material_version_id": material.active_version_id,
            "chunk_range": [],
            "resolution_status": "resolved",
            "resolution_method": "single_ready_material" if len(candidates) == 1 else "semantic_score",
            "match_score": selected["score"] if selected else 0,
            "match_reasons": selected["reasons"] if selected else [],
            "candidates": candidates,
            "completion_mode": "loaded_and_confirmed",
        }
    if task_type == "review":
        point = _choose(
            db.query(KnowledgePoint).filter(KnowledgePoint.course_id == course_id, KnowledgePoint.status == "active").order_by(KnowledgePoint.id).all(),
            title,
            used_ids,
        )
        if point is None:
            return "knowledge_point", None, {"knowledge_point_id": None, "source_chunk_ids": [], "resolution_status": "unresolved", "review_mode": "loaded_and_confirmed", "remediation": "请先生成知识点或选择目标"}
        try:
            source_ids = json.loads(point.source_chunk_ids or "[]")
        except (json.JSONDecodeError, TypeError):
            source_ids = []
        source_material_public_ids = [
            public_id for (public_id,) in db.query(Material.public_id)
            .join(MaterialChunk, MaterialChunk.material_id == Material.id)
            .filter(MaterialChunk.id.in_(source_ids)).order_by(Material.id).distinct().all()
        ] if source_ids else []
        return "knowledge_point", point.id, {
            "knowledge_point_id": point.id,
            "source_chunk_ids": source_ids,
            "source_material_public_ids": source_material_public_ids,
            "material_public_id": source_material_public_ids[0] if source_material_public_ids else None,
            "resolution_status": "resolved",
            "review_mode": "loaded_and_confirmed",
        }
    return "quiz", None, {
        "knowledge_point_ids": [],
        "question_count": 5,
        "pass_score": 60,
        "retry_policy": "create_new_quiz",
        "history_quiz_ids": [],
    }


def ensure_target_spec(db: Session, task) -> dict[str, Any]:
    """Backfill a minimal compatible spec without changing a legacy target."""
    try:
        current = json.loads(task.target_spec_json or "{}")
    except (json.JSONDecodeError, TypeError):
        current = {}
    if isinstance(current, dict) and current:
        return current
    target_type = task.target_type or task.task_type
    if target_type == "material":
        spec = {"material_id": task.target_id, "material_version_id": None, "chunk_range": [], "completion_mode": "opened_and_confirmed"}
    elif target_type == "knowledge_point":
        spec = {"knowledge_point_id": task.target_id, "source_chunk_ids": [], "review_mode": "viewed_and_confirmed"}
    else:
        spec = {"knowledge_point_ids": [], "question_count": 5, "pass_score": 60, "retry_policy": "create_new_quiz", "history_quiz_ids": []}
    task.target_spec_json = json.dumps(spec, ensure_ascii=False)
    return spec
