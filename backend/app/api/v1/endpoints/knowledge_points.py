"""Knowledge-point generation and list endpoints.

``POST /api/v1/courses/{course_id}/knowledge-points/generate`` runs the
``OutlineAgent`` over the course's ready-material chunks, persists the
extracted points to the ``knowledge_points`` table, and returns them.

V6-30: regeneration uses a generation-based versioning model.  Each
call archives all currently-active KPs (``status='archived'``) and
creates new active KPs with an incremented ``generation`` number.  Old
KPs are never deleted, so historical quiz results, weak-point records,
and graph links remain valid.  The response includes ``generation``
(the new version number) and ``archived_count`` (how many old KPs were
archived).

``GET /api/v1/courses/{course_id}/knowledge-points`` returns the
persisted active points for a course.  Pass ``include_archived=true``
to also see archived (historical) points.

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
from app.agents.outline import OutlineContractError, generate as outline_generate
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessException, NotFoundException
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
from app.services.real_llm_acceptance_service import RealLLMAcceptanceError, assert_real_llm_meta

logger = logging.getLogger(__name__)
router = APIRouter()

_PROMPT_VERSION = "outline_v1"


def _with_public_material_ids(db: Session, points: list[KnowledgePointResponse]) -> list[KnowledgePointResponse]:
    """Attach stable material identities for each knowledge-point source."""
    chunk_ids = {chunk_id for point in points for chunk_id in point.source_chunk_ids}
    if not chunk_ids:
        return points
    rows = (
        db.query(MaterialChunk.id, Material.public_id)
        .join(Material, Material.id == MaterialChunk.material_id)
        .filter(MaterialChunk.id.in_(chunk_ids))
        .all()
    )
    public_by_chunk = {chunk_id: public_id for chunk_id, public_id in rows}
    enriched = []
    for point in points:
        public_ids = list(dict.fromkeys(
            public_by_chunk[chunk_id] for chunk_id in point.source_chunk_ids
            if chunk_id in public_by_chunk
        ))
        enriched.append(point.model_copy(update={
            "source_material_public_ids": public_ids,
            "material_public_id": public_ids[0] if public_ids else None,
        }))
    return enriched


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
        generated_outline = outline_generate(
            db, course_id, course.name, user_config=user_config, return_meta=True
        )
        # ``return_meta`` is an additive R4 contract. Keep the endpoint
        # compatible with test seams and integrations that replace the agent
        # with the historic list-only return value.
        if isinstance(generated_outline, tuple):
            points, llm_meta = generated_outline
        else:
            points = generated_outline
            llm_meta = {
                "meta_observed": False,
                "requested_provider": provider,
                "requested_model": model_name,
                "actual_provider": "unknown",
                "actual_model": None,
                "fallback_used": None,
                "degraded": True,
                "fallback_reason": "LLM_META_NOT_OBSERVED",
            }
        if settings.REAL_LLM_ACCEPTANCE_MODE:
            assert_real_llm_meta(llm_meta)
    except OutlineContractError as exc:
        _safe_finish_run(
            db,
            run_id=run_id,
            status="failed",
            error_message=str(exc),
            started_at=run_started_at,
        )
        raise BusinessException(message=str(exc), status_code=422)
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
    AgentAudit.update_run_meta(
        db, run_id, llm_meta.get("actual_model"), llm_meta.get("actual_provider"), llm_meta
    )
    _safe_add_step(
        db,
        run_id=run_id,
        step_name="generate",
        step_index=0,
        input_data={"prompt_version": _PROMPT_VERSION},
        output_data={
            "knowledge_point_count": len(points),
            "initial_contract": llm_meta.get("initial_contract"),
            "repair_attempted": bool(llm_meta.get("repair_attempted")),
            "repair_contract": llm_meta.get("repair_contract"),
            "llm_call_count": llm_meta.get("llm_call_count", 1),
        },
        duration_ms=generate_duration,
    )

    # Keep active rows untouched until a valid replacement generation is
    # staged.  Generation failure must never leave the learner without an
    # active outline.
    existing_active = (
        db.query(KnowledgePoint)
        .filter(
            KnowledgePoint.course_id == course_id,
            KnowledgePoint.user_id == current_user.id,
            KnowledgePoint.status == "active",
        )
        .all()
    )
    archived_count = len(existing_active)

    # An empty outline is not a safe replacement for an existing outline.
    # On a first-ever generation, retain a minimal evidence-backed fallback
    # instead of creating an unusable empty course; on regeneration we keep
    # the active generation and return the explicit failure below.
    if not points:
        if archived_count > 0:
            # V7.4-05: Regeneration with empty result — preserve existing
            # active KPs and return an explicit failure.
            db.rollback()
            raise BusinessException(
                message="生成失败：未产生有效知识点，已保留当前提纲",
                status_code=422,
            )
        fallback_chunk = (
            db.query(MaterialChunk)
            .join(Material, Material.id == MaterialChunk.material_id)
            .filter(
                MaterialChunk.course_id == course_id,
                Material.status == "ready",
                MaterialChunk.is_active == 1,
                MaterialChunk.is_indexable == 1,
            )
            .order_by(MaterialChunk.id.asc())
            .first()
        )
        if fallback_chunk is not None:
            content = (fallback_chunk.text or "课程核心知识").strip()
            title = (fallback_chunk.title or content.splitlines()[0] or "课程核心知识").strip()[:255]
            points = [{
                "title": title,
                "summary": content[:500],
                "importance": 3,
                "source_chunk_ids": [fallback_chunk.id],
                "exam_style": "基于资料说明核心概念",
                "review_action": "阅读来源片段并复述要点",
            }]

    # Compute the next generation number (max across all KPs for this
    # course, including archived ones).
    max_gen_row = (
        db.query(KnowledgePoint)
        .filter(
            KnowledgePoint.course_id == course_id,
            KnowledgePoint.user_id == current_user.id,
        )
        .order_by(KnowledgePoint.generation.desc())
        .first()
    )
    next_generation = (max_gen_row.generation + 1) if max_gen_row else 1

    persisted: list[KnowledgePointResponse] = []
    dropped = 0
    drop_reasons: list[str] = []
    seen: set[str] = set()  # dedup within this generation
    for point in points:
        source_ids = [int(value) for value in point.get("source_chunk_ids", []) if str(value).isdigit()]
        valid_source_ids = [row[0] for row in db.query(MaterialChunk.id).join(Material, Material.id == MaterialChunk.material_id).filter(
            MaterialChunk.id.in_(source_ids), MaterialChunk.course_id == course_id,
            Material.status == "ready", MaterialChunk.is_active == 1, MaterialChunk.is_indexable == 1,
        ).all()] if source_ids else []
        if not valid_source_ids:
            dropped += 1
            drop_reasons.append("unverified_or_inactive_source")
            continue
        normalized = re.sub(r"\s+", "", point["title"].strip().lower())
        stable_key = f"{course_id}:{normalized}"
        # Dedup within this generation (same normalized title)
        if stable_key in seen:
            continue
        seen.add(stable_key)
        # Stage a new generation first; old rows are archived only after
        # at least one valid replacement exists in this transaction.
        row = KnowledgePoint(
            course_id=course_id, user_id=current_user.id,
            stable_key=stable_key, title_normalized=normalized,
            generation=next_generation,
        )
        db.add(row)
        row.title = point["title"]
        row.summary = point["summary"]
        row.importance = point["importance"]
        row.source_chunk_ids = json.dumps(valid_source_ids)
        row.source_version_ids = json.dumps(sorted({
            c.material_version_id for c in db.query(MaterialChunk).filter(
                MaterialChunk.id.in_(valid_source_ids)
            ) if c.material_version_id
        }))
        row.exam_style = point["exam_style"]
        row.review_action = point["review_action"]
        row.status = "active"
        db.flush()
        persisted.append(KnowledgePointResponse.model_validate(row))

    if not persisted:
        db.rollback()
        raise BusinessException(
            message="未生成包含有效资料证据的知识点，已保留当前提纲",
            status_code=422,
        )

    for row in existing_active:
        row.status = "archived"

    db.commit()

    _safe_finish_run(
        db,
        run_id=run_id,
        status="degraded" if llm_meta.get("degraded") else "success",
        output_summary={
            "knowledge_point_count": len(persisted),
            "meta_observed": llm_meta.get("meta_observed") is True,
            "initial_contract": llm_meta.get("initial_contract"),
            "repair_attempted": bool(llm_meta.get("repair_attempted")),
            "repair_success": bool(llm_meta.get("repair_success")),
            "repair_contract": llm_meta.get("repair_contract"),
            "llm_call_count": llm_meta.get("llm_call_count", 1),
        },
        duration_ms=int((time.monotonic() - run_started_at) * 1000),
    )

    return GenerateKnowledgePointsResponse(
        knowledge_points=_with_public_material_ids(db, persisted),
        count=len(persisted),
        requested=len(points),
        generated=len(persisted),
        dropped=dropped,
        drop_reasons=sorted(set(drop_reasons)),
        generation=next_generation,
        archived_count=archived_count,
    )


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
    items = _with_public_material_ids(db, [KnowledgePointResponse.model_validate(r) for r in rows])
    return KnowledgePointListResponse(items=items, total=len(items))


@router.get(
    "/{course_id}/knowledge-points/generations",
)
def list_kp_generations(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """V7.4-05: List all knowledge-point generations with metadata.

    Returns a list of ``{generation, status, count, created_at}`` dicts,
    one per generation, sorted by generation descending.
    """
    _get_owned_course(db, course_id, current_user.id)

    rows = (
        db.query(KnowledgePoint)
        .filter(
            KnowledgePoint.course_id == course_id,
            KnowledgePoint.user_id == current_user.id,
        )
        .order_by(KnowledgePoint.generation.desc())
        .all()
    )
    # Group by generation
    gen_map: dict[int, dict] = {}
    for row in rows:
        if row.generation not in gen_map:
            gen_map[row.generation] = {
                "generation": row.generation,
                "status": row.status,
                "count": 0,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        gen_map[row.generation]["count"] += 1
        # If any KP in this generation is active, the generation is active
        if row.status == "active":
            gen_map[row.generation]["status"] = "active"

    return list(gen_map.values())


@router.get(
    "/{course_id}/knowledge-points/generations/{generation}",
    response_model=KnowledgePointListResponse,
)
def list_kps_by_generation(
    course_id: int,
    generation: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgePointListResponse:
    """V7.4.2-07: List knowledge points for a specific generation.

    Returns all KPs (both active and archived) belonging to the given
    generation number, allowing the frontend to display a read-only
    historical view of any past generation.
    """
    _get_owned_course(db, course_id, current_user.id)

    rows = (
        db.query(KnowledgePoint)
        .filter(
            KnowledgePoint.course_id == course_id,
            KnowledgePoint.user_id == current_user.id,
            KnowledgePoint.generation == generation,
        )
        .order_by(KnowledgePoint.id.asc())
        .all()
    )
    items = _with_public_material_ids(db, [KnowledgePointResponse.model_validate(r) for r in rows])
    is_active_generation = any(row.status == "active" for row in rows)
    return KnowledgePointListResponse(
        items=items,
        total=len(items),
        read_only=not is_active_generation,
        generation_status="active" if is_active_generation else "archived",
    )


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
