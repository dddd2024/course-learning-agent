"""Deterministic, persisted target selection for executable study tasks."""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", value or "")}


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
    return ranked[0]


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
            return "material", None, {"material_id": None, "completion_mode": "opened_and_confirmed", "remediation": "请先上传并解析课程资料"}
        return "material", material.id, {
            "material_id": material.id,
            "material_version_id": material.active_version_id,
            "chunk_range": [],
            "completion_mode": "opened_and_confirmed",
        }
    if task_type == "review":
        point = _choose(
            db.query(KnowledgePoint).filter(KnowledgePoint.course_id == course_id, KnowledgePoint.status == "active").order_by(KnowledgePoint.id).all(),
            title,
            used_ids,
        )
        if point is None:
            return "knowledge_point", None, {"knowledge_point_id": None, "source_chunk_ids": [], "review_mode": "viewed_and_confirmed", "remediation": "请先生成知识点"}
        try:
            source_ids = json.loads(point.source_chunk_ids or "[]")
        except (json.JSONDecodeError, TypeError):
            source_ids = []
        return "knowledge_point", point.id, {
            "knowledge_point_id": point.id,
            "source_chunk_ids": source_ids,
            "review_mode": "viewed_and_confirmed",
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
