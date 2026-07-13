"""Deterministic, persisted target selection for executable study tasks."""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material


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


def resolve_target(
    db: Session, course_id: int, task_type: str, title: str, used_ids: set[int] | None = None
) -> tuple[str, int | None, dict[str, Any]]:
    """Return a stable target type/id plus a complete persisted target spec."""
    used_ids = used_ids or set()
    if task_type == "learn":
        material = _choose(
            db.query(Material).filter(Material.course_id == course_id, Material.status == "ready").order_by(Material.id).all(),
            title,
            used_ids,
        )
        if material is None:
            return "material", None, {"material_id": None, "resolution_status": "unresolved", "completion_mode": "loaded_and_confirmed", "remediation": "请先上传并解析课程资料或选择目标"}
        return "material", material.id, {
            "material_id": material.id,
            "material_version_id": material.active_version_id,
            "chunk_range": [],
            "resolution_status": "resolved",
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
        return "knowledge_point", point.id, {
            "knowledge_point_id": point.id,
            "source_chunk_ids": source_ids,
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
