"""Persistent local-worker orchestration for material parsing."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.timezone import utc_now
from app.models.material import Material
from app.models.parse_job import ParseJob
from app.services.material_parser import parse_with_retry
from app.services.error_logger import log_error

ACTIVE = {"queued", "running"}


def create_or_get_job(db: Session, material: Material, user_id: int, *, include_created: bool = False):
    existing = (db.query(ParseJob).filter(ParseJob.material_id == material.id, ParseJob.status.in_(ACTIVE)).order_by(ParseJob.id.desc()).first())
    if existing:
        return (existing, False) if include_created else existing
    job = ParseJob(material_id=material.id, material_version_id=material.active_version_id, user_id=user_id, status="queued")
    db.add(job)
    material.status = "processing"
    material.error_message = None
    material.parse_started_at = utc_now()
    db.commit()
    db.refresh(job)
    return (job, True) if include_created else job


def claim_next_job(db: Session) -> ParseJob | None:
    """Atomically claim the oldest queued job using a conditional UPDATE.

    Finds the oldest ``queued`` job, then issues::

        UPDATE parse_jobs SET status='running', started_at=NOW(), heartbeat_at=NOW()
        WHERE id = <job_id> AND status = 'queued'

    The ``AND status = 'queued'`` guard prevents a race where two workers
    select the same row: only the first UPDATE succeeds (rowcount=1),
    the second gets rowcount=0 and returns ``None``.
    """
    job = (
        db.query(ParseJob)
        .filter(ParseJob.status == "queued")
        .order_by(ParseJob.created_at)
        .first()
    )
    if job is None:
        return None
    now = utc_now()
    result = db.execute(
        update(ParseJob)
        .where(ParseJob.id == job.id, ParseJob.status == "queued")
        .values(status="running", started_at=now, heartbeat_at=now)
    )
    if result.rowcount == 0:
        # Another worker claimed it between our SELECT and UPDATE.
        return None
    db.commit()
    return db.get(ParseJob, job.id)


def run_job(job_id: int, parse_fn=None) -> None:
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        job = db.query(ParseJob).filter(ParseJob.id == job_id).first()
        if job is None or job.status == "cancelled":
            return
        material = db.query(Material).filter(Material.id == job.material_id, Material.user_id == job.user_id).first()
        if material is None:
            job.status, job.error_message, job.finished_at = "failed", "资料不存在", utc_now()
            db.commit(); return
        job.status, job.started_at, job.heartbeat_at = "running", utc_now(), utc_now()
        job.attempt += 1
        db.commit()
        status, _ = (parse_fn or parse_with_retry)(db, material, job.user_id)
        # A job is queued before a new parsed version exists.  Bind it after
        # parsing succeeds so readiness can prove that its terminal state and
        # the material's active version describe the same artifact.
        db.refresh(material)
        db.refresh(job)
        if status == "ready":
            job.material_version_id = material.active_version_id
        if job.status != "cancelled" and status != "cancelled":
            job.status = "succeeded" if status == "ready" else "failed"
            job.finished_at, job.heartbeat_at = utc_now(), utc_now()
            job.error_message = material.last_parse_error if status != "ready" else None
            db.commit()
    except Exception as exc:  # pragma: no cover - crash guard
        db.rollback()
        job = db.query(ParseJob).filter(ParseJob.id == job_id).first()
        if job:
            job.status, job.error_message, job.finished_at = "failed", str(exc), utc_now()
            material = db.query(Material).filter(Material.id == job.material_id).first()
            if material is not None:
                material.status = "failed"
                material.error_message = "后台解析任务异常，请查看日志中心"
                material.last_parse_error = str(exc)
                material.parse_finished_at = utc_now()
                log_error(db, job.user_id, category="parse", level="error", title="后台解析任务异常",
                          message=str(exc), technical_detail=f"{exc.__class__.__name__}: {exc}",
                          course_id=material.course_id, material_id=material.id, commit=False)
            db.commit()
    finally:
        db.close()


def recover_stale_jobs(db: Session, timeout_seconds: int = 600) -> int:
    """Re-queue running jobs whose heartbeat is older than ``timeout_seconds``.

    V6-50: stale running jobs are reset to ``queued`` (not ``failed``) so
    the persistent worker can pick them up again.  The material is also
    reset to ``uploaded`` so the UI shows the correct state.
    """
    threshold = utc_now() - timedelta(seconds=timeout_seconds)
    stale = db.query(ParseJob).filter(ParseJob.status == "running", ParseJob.heartbeat_at < threshold).all()
    for job in stale:
        job.status = "queued"
        job.error_message = "解析 worker 心跳超时，已重新排队"
        job.started_at = None
        job.heartbeat_at = None
        job.finished_at = None
        material = db.query(Material).filter(Material.id == job.material_id).first()
        if material and material.status == "processing":
            material.status = "uploaded"
            material.last_parse_error = job.error_message
    if stale:
        db.commit()
    return len(stale)
