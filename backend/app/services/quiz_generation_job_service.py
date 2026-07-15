"""Durable, bounded asynchronous quiz-generation orchestration."""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BusinessException, NotFoundException
from app.core.timezone import utc_now
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.plan import StudyGoal, StudyTask
from app.models.quiz_generation_job import QuizGenerationJob
from app.services.quiz_creation_service import QuizCreationService, resolve_quiz_contract
from app.services.task_state_machine import transition_task
from app.services.task_target_resolver import ensure_target_spec

ACTIVE_JOB_STATUSES = {"queued", "running"}


def _owned_course(db: Session, course_id: int, user_id: int) -> Course:
    course = db.query(Course).filter(Course.id == course_id, Course.user_id == user_id).first()
    if course is None:
        raise NotFoundException(message="课程不存在")
    return course


def _active_points(db: Session, course_id: int, user_id: int, point_ids: list[int] | None) -> list[KnowledgePoint]:
    query = db.query(KnowledgePoint).filter(
        KnowledgePoint.course_id == course_id,
        KnowledgePoint.user_id == user_id,
        KnowledgePoint.status == "active",
    )
    if point_ids:
        query = query.filter(KnowledgePoint.id.in_(point_ids))
    rows = query.order_by(KnowledgePoint.id.asc()).all()
    if point_ids and len(rows) != len(set(point_ids)):
        raise BusinessException(message="包含无效或已归档的知识点", status_code=422)
    if not rows:
        raise BusinessException(message="课程暂无知识点，请先生成知识点", status_code=422)
    return rows


def create_generation_job(
    db: Session,
    *,
    user_id: int,
    course_id: int,
    knowledge_point_ids: list[int] | None,
    question_count: int,
    pass_score: int,
    question_types: list[str] | None,
    difficulty_distribution: dict[str, int] | None,
    task_id: int | None = None,
) -> QuizGenerationJob:
    """Validate all inputs and persist a queued job before work begins."""
    _owned_course(db, course_id, user_id)
    rows = _active_points(db, course_id, user_id, knowledge_point_ids)
    contract = resolve_quiz_contract(question_count, question_types, difficulty_distribution, pass_score)
    if task_id is not None:
        existing = db.query(QuizGenerationJob).filter(
            QuizGenerationJob.task_id == task_id,
            QuizGenerationJob.user_id == user_id,
            QuizGenerationJob.status.in_(ACTIVE_JOB_STATUSES),
        ).order_by(QuizGenerationJob.id.desc()).first()
        if existing is not None:
            return existing
    payload = {
        "knowledge_point_ids": [row.id for row in rows],
        "question_count": contract.question_count,
        "pass_score": contract.pass_score,
        "question_types": list(contract.question_types),
        "difficulty_distribution": dict(contract.difficulty_distribution),
    }
    job = QuizGenerationJob(
        user_id=user_id,
        course_id=course_id,
        task_id=task_id,
        status="queued",
        progress_stage="preparing",
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def create_task_generation_job(db: Session, task_id: int, user_id: int) -> QuizGenerationJob:
    task = db.query(StudyTask).join(StudyGoal, StudyGoal.id == StudyTask.goal_id).filter(
        StudyTask.id == task_id,
        StudyGoal.user_id == user_id,
    ).first()
    if task is None:
        raise NotFoundException(message="任务不存在")
    if task.task_type != "quiz" or task.target_type != "quiz":
        raise BusinessException(message="该任务不是可生成的测验任务", status_code=422)
    if task.target_id is not None:
        raise BusinessException(message="该任务已绑定测验", status_code=409)
    spec = ensure_target_spec(db, task)
    point_ids = [int(value) for value in spec.get("knowledge_point_ids", []) if str(value).isdigit()]
    return create_generation_job(
        db,
        user_id=user_id,
        course_id=task.course_id,
        knowledge_point_ids=point_ids or None,
        question_count=max(1, int(spec.get("question_count", 5))),
        pass_score=int(spec.get("pass_score", 60)),
        question_types=spec.get("question_types"),
        difficulty_distribution=spec.get("difficulty_distribution"),
        task_id=task.id,
    )


def get_owned_job(db: Session, job_id: int, user_id: int) -> QuizGenerationJob:
    job = db.query(QuizGenerationJob).filter(
        QuizGenerationJob.id == job_id,
        QuizGenerationJob.user_id == user_id,
    ).first()
    if job is None:
        raise NotFoundException(message="测验生成任务不存在")
    return job


def recover_stale_job(db: Session, job: QuizGenerationJob) -> bool:
    if job.status != "running" or job.heartbeat_at is None:
        return False
    stale_after = float(settings.QUIZ_GENERATION_TOTAL_BUDGET_SECONDS) + 60
    threshold = utc_now() - timedelta(seconds=stale_after)
    # SQLite returns naive datetimes even for timezone-aware ORM columns.
    if job.heartbeat_at.tzinfo is None and threshold.tzinfo is not None:
        threshold = threshold.replace(tzinfo=None)
    if job.heartbeat_at >= threshold:
        return False
    job.status = "queued"
    job.progress_stage = "preparing"
    job.started_at = None
    job.heartbeat_at = None
    job.error_code = "WORKER_RESTARTED"
    job.error_message = "生成进程中断，已自动重新排队"
    db.commit()
    return True


def run_generation_job(job_id: int) -> None:
    """Atomically claim and execute one job in FastAPI's thread pool."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    telemetry: dict[str, Any] = {}
    try:
        now = utc_now()
        claimed = db.execute(
            update(QuizGenerationJob)
            .where(QuizGenerationJob.id == job_id, QuizGenerationJob.status == "queued")
            .values(status="running", progress_stage="generating", started_at=now, heartbeat_at=now)
        )
        if claimed.rowcount == 0:
            db.rollback()
            return
        db.commit()
        job = db.get(QuizGenerationJob, job_id)
        payload = json.loads(job.payload_json)
        course = _owned_course(db, job.course_id, job.user_id)
        points = _active_points(db, job.course_id, job.user_id, payload["knowledge_point_ids"])
        quiz = QuizCreationService.create_quiz(
            db=db,
            user_id=job.user_id,
            course_id=job.course_id,
            course_name=course.name,
            knowledge_points=points,
            question_count=payload["question_count"],
            pass_score=payload["pass_score"],
            question_types=payload["question_types"],
            difficulty_distribution=payload["difficulty_distribution"],
            telemetry=telemetry,
        )
        job.progress_stage = "saving"
        job.provider_calls = int(telemetry.get("provider_calls", 0))
        db.flush()
        if job.task_id is not None:
            task = db.query(StudyTask).join(StudyGoal, StudyGoal.id == StudyTask.goal_id).filter(
                StudyTask.id == job.task_id,
                StudyGoal.user_id == job.user_id,
                StudyTask.course_id == job.course_id,
            ).first()
            if task is None or task.target_type != "quiz" or task.target_id is not None:
                raise BusinessException(message="计划任务状态已变化，未绑定新测验", status_code=409)
            task.target_id = quiz.id
            if task.execution_status == "pending":
                transition_task(db, task, "start", job.user_id, commit=False)
        job.quiz_id = quiz.id
        job.status = "succeeded"
        job.progress_stage = "completed"
        job.heartbeat_at = job.finished_at = utc_now()
        job.error_code = job.error_message = None
        db.commit()
    except Exception as exc:  # the job row is the durable failure contract
        db.rollback()
        job = db.get(QuizGenerationJob, job_id)
        if job is not None:
            job.status = "failed"
            job.progress_stage = "failed"
            job.provider_calls = int(telemetry.get("provider_calls", 0))
            job.error_code = getattr(exc, "code", "QUIZ_GENERATION_FAILED")
            message = getattr(exc, "message", None) or str(exc) or "测验生成失败"
            details = getattr(exc, "data", None)
            if isinstance(details, dict):
                valid = details.get("valid_count")
                requested = details.get("requested_count")
                reasons = details.get("drop_reasons") or []
                if valid is not None and requested is not None:
                    message += f"：仅生成 {valid}/{requested} 道有效题"
                if reasons:
                    message += "；原因 " + ", ".join(str(reason) for reason in reasons[:5])
            job.error_message = message
            job.heartbeat_at = job.finished_at = utc_now()
            db.commit()
    finally:
        db.close()
