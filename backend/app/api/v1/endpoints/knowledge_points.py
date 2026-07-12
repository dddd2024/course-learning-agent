"""Knowledge-point generation and list endpoints.

``POST /api/v1/courses/{course_id}/knowledge-points/generate`` runs the
``OutlineAgent`` over the course's ready-material chunks, persists the
extracted points to the ``knowledge_points`` table (replacing any
existing points for the course), and returns them.

``GET /api/v1/courses/{course_id}/knowledge-points`` returns the
persisted points for a course.

All queries are scoped by ``current_user.id`` so a course owned by
another user is invisible (returned as 404) so existence is never
leaked.
"""
import json
import logging
import time
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.audit import AgentAudit
from app.agents.outline import generate as outline_generate
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.quiz import WeakPoint
from app.models.user import User
from app.schemas.knowledge_point import (
    GenerateKnowledgePointsResponse,
    KnowledgePointListResponse,
    KnowledgePointResponse,
)
from app.services.llm_config_service import (
    build_user_config,
    get_active_config,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_PROMPT_VERSION = "outline_v1"


def _get_owned_course(db: Session, course_id: int, user_id: int) -> Course:
    """Return the course if it belongs to ``user_id``, else 404."""
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.user_id == user_id)
        .first()
    )
    if course is None:
        raise NotFoundException(message="课程不存在")
    return course


@router.post(
    "/{course_id}/knowledge-points/generate",
    response_model=GenerateKnowledgePointsResponse,
)
def generate_knowledge_points(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GenerateKnowledgePointsResponse:
    """Generate and persist knowledge points for a course's materials."""
    course = _get_owned_course(db, course_id, current_user.id)

    # T06: refuse to generate knowledge points for a course with no
    # parsed materials. Without this guard the mock LLM would happily
    # fabricate points for an empty course, misleading the user.
    ready_chunk_count = (
        db.query(MaterialChunk)
        .join(Material, MaterialChunk.material_id == Material.id)
        .filter(
            Material.course_id == course_id,
            Material.status == "ready",
            MaterialChunk.is_active == 1,
            MaterialChunk.is_indexable == 1,
        )
        .count()
    )
    if ready_chunk_count == 0:
        raise HTTPException(
            status_code=400,
            detail="该课程还没有已解析的资料，请先上传并解析材料后再生成知识点。",
        )

    active_config = get_active_config(db, current_user.id)
    user_config = build_user_config(active_config) if active_config else None
    provider = (
        "user"
        if active_config
        else ("real" if settings.LLM_PROVIDER == "real" else "mock")
    )
    config_id = active_config.id if active_config else None
    model_name = active_config.model if active_config else settings.LLM_MODEL

    run_started_at = time.monotonic()
    run_id: int | None = None
    try:
        run = AgentAudit.create_run(
            db,
            user_id=current_user.id,
            run_type="outline",
            input_summary={"course_id": course_id, "course_name": course.name},
            prompt_version=_PROMPT_VERSION,
            model_name=model_name,
            provider=provider,
            config_id=config_id,
        )
        run_id = run.id
        db.commit()
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.create_run failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass

    generate_started = time.monotonic()
    try:
        points = outline_generate(
            db, course_id, course.name, user_config=user_config
        )
    except Exception as exc:
        _safe_finish_run(
            db,
            run_id=run_id,
            status="failed",
            error_message=str(exc),
            started_at=run_started_at,
        )
        raise
    generate_duration = int((time.monotonic() - generate_started) * 1000)
    _safe_add_step(
        db,
        run_id=run_id,
        step_name="generate",
        step_index=0,
        input_data={"prompt_version": _PROMPT_VERSION},
        output_data={"knowledge_point_count": len(points)},
        duration_ms=generate_duration,
    )

    # Merge by a stable course+normalised-title identity.  Historical quiz,
    # weak-point and graph links therefore keep their original KP IDs.
    existing = {
        row.stable_key: row for row in db.query(KnowledgePoint).filter(
            KnowledgePoint.course_id == course_id,
            KnowledgePoint.user_id == current_user.id,
        ) if row.stable_key
    }
    seen: set[str] = set()
    persisted: list[KnowledgePointResponse] = []
    for point in points:
        normalized = re.sub(r"\s+", "", point["title"].strip().lower())
        stable_key = f"{course_id}:{normalized}"
        seen.add(stable_key)
        row = existing.get(stable_key)
        if row is None:
            row = KnowledgePoint(
                course_id=course_id, user_id=current_user.id,
                stable_key=stable_key, title_normalized=normalized,
            )
            db.add(row)
        row.title = point["title"]
        row.summary = point["summary"]
        row.importance = point["importance"]
        row.source_chunk_ids = json.dumps(point["source_chunk_ids"])
        row.source_version_ids = json.dumps(sorted({
            c.material_version_id for c in db.query(MaterialChunk).filter(
                MaterialChunk.id.in_(point["source_chunk_ids"])
            ) if c.material_version_id
        }))
        row.exam_style = point["exam_style"]
        row.review_action = point["review_action"]
        row.status = "active"
        db.flush()
        persisted.append(KnowledgePointResponse.model_validate(row))

    for key, row in existing.items():
        if key not in seen:
            row.status = "archived"

    db.commit()

    _safe_finish_run(
        db,
        run_id=run_id,
        status="success",
        output_summary={"knowledge_point_count": len(persisted)},
        duration_ms=int((time.monotonic() - run_started_at) * 1000),
    )

    return GenerateKnowledgePointsResponse(knowledge_points=persisted)


@router.get(
    "/{course_id}/knowledge-points",
    response_model=KnowledgePointListResponse,
)
def list_knowledge_points(
    course_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgePointListResponse:
    """List persisted knowledge points for a course owned by the user."""
    _get_owned_course(db, course_id, current_user.id)

    query = db.query(KnowledgePoint).filter(
        KnowledgePoint.course_id == course_id,
        KnowledgePoint.user_id == current_user.id,
    )
    if not include_archived:
        query = query.filter(KnowledgePoint.status == "active")
    rows = query.order_by(KnowledgePoint.id.asc()).all()
    items = [KnowledgePointResponse.model_validate(r) for r in rows]
    return KnowledgePointListResponse(items=items, total=len(items))


def _safe_add_step(
    db: Session,
    run_id: int | None,
    step_name: str,
    step_index: int,
    input_data=None,
    output_data=None,
    duration_ms: int | None = None,
    status: str = "success",
) -> None:
    """Add an audit step, swallowing any error so the main flow runs on."""
    if run_id is None:
        return
    try:
        AgentAudit.add_step(
            db,
            run_id=run_id,
            step_name=step_name,
            step_index=step_index,
            input_data=input_data,
            output_data=output_data,
            duration_ms=duration_ms,
            status=status,
        )
        db.commit()
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.add_step(%s) failed: %s", step_name, exc)
        try:
            db.rollback()
        except Exception:
            pass


def _safe_finish_run(
    db: Session,
    run_id: int | None,
    status: str,
    output_summary=None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    started_at: float | None = None,
) -> None:
    """Finish an audit run, swallowing any error so the main flow runs on."""
    if run_id is None:
        return
    if duration_ms is None and started_at is not None:
        duration_ms = int((time.monotonic() - started_at) * 1000)
    try:
        AgentAudit.finish_run(
            db,
            run_id=run_id,
            status=status,
            output_summary=output_summary,
            duration_ms=duration_ms,
            error_message=error_message,
        )
        db.commit()
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.finish_run failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
