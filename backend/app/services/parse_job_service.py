"""Persistent local-worker orchestration for material parsing."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.timezone import utc_now
from app.models.material import Material
from app.models.parse_job import ParseJob
from app.services.material_parser import parse_with_retry

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


def run_job(job_id: int) -> None:
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
        status, _ = parse_with_retry(db, material, job.user_id)
        db.refresh(job)
        if job.status != "cancelled":
            job.status = "succeeded" if status == "ready" else "failed"
            job.finished_at, job.heartbeat_at = utc_now(), utc_now()
            job.error_message = material.last_parse_error if status != "ready" else None
            db.commit()
    except Exception as exc:  # pragma: no cover - crash guard
        db.rollback()
        job = db.query(ParseJob).filter(ParseJob.id == job_id).first()
        if job:
            job.status, job.error_message, job.finished_at = "failed", str(exc), utc_now()
            db.commit()
    finally:
        db.close()


def recover_stale_jobs(db: Session, timeout_seconds: int = 600) -> int:
    threshold = utc_now() - timedelta(seconds=timeout_seconds)
    stale = db.query(ParseJob).filter(ParseJob.status == "running", ParseJob.heartbeat_at < threshold).all()
    for job in stale:
        job.status, job.error_message, job.finished_at = "failed", "解析 worker 心跳超时，可重试", utc_now()
        material = db.query(Material).filter(Material.id == job.material_id).first()
        if material and material.status == "processing":
            material.status, material.last_parse_error = "failed", job.error_message
    if stale:
        db.commit()
    return len(stale)
