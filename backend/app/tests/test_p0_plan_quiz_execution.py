"""P0 regression coverage for executable plan targets and bounded quiz jobs."""
import json
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import BusinessException, NotFoundException, QuizConstraintException
from app.core.config import settings
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.plan import StudyGoal, StudyTask
from app.models.quiz import Quiz
from app.models.quiz_generation_job import QuizGenerationJob
from app.models.user import User
from app.services.quiz_creation_service import QuizCreationService
from app.services.quiz_generation_job_service import create_task_generation_job, run_generation_job
from app.services.task_execution_service import bind_task_target, start_task
from app.services.task_target_resolver import resolve_target


def _material(db, user, course, filename, text=""):
    material = Material(user_id=user.id, course_id=course.id, filename=filename, file_type="pdf", file_path=filename, status="ready")
    db.add(material); db.flush()
    version = MaterialVersion(material_id=material.id, version=1, status="ready")
    db.add(version); db.flush()
    material.active_version_id = version.id
    if text:
        db.add(MaterialChunk(material_id=material.id, material_version_id=version.id, course_id=course.id, chunk_index=0, title=text[:80], text=text, keyword_text=text, is_active=1))
    db.commit()
    return material


@pytest.mark.parametrize("title,filename", [
    ("学习网络层：IP协议与路由", "Chap4 Network Layer.pdf"),
    ("学习传输层：TCP与UDP", "Chap3 Transport Layer.pdf"),
    ("学习数据链路层：帧与MAC", "Chap5 Data Link Layer.pdf"),
    ("学习物理层：信号与编码", "Chap7 Physical Layer.pdf"),
])
def test_bilingual_material_resolution(db_session, sample_user, sample_course, title, filename):
    wanted = _material(db_session, sample_user, sample_course, filename)
    _material(db_session, sample_user, sample_course, "Unrelated Appendix.pdf", "课程作业说明")
    kind, target_id, spec = resolve_target(db_session, sample_course.id, "learn", title)
    assert (kind, target_id) == ("material", wanted.id)
    assert spec["match_score"] >= 8
    assert spec["match_reasons"]


def test_single_ready_fallback_and_ambiguous_no_guess(db_session, sample_user, sample_course):
    only = _material(db_session, sample_user, sample_course, "opaque-a.pdf")
    assert resolve_target(db_session, sample_course.id, "learn", "学习陌生主题")[1] == only.id
    _material(db_session, sample_user, sample_course, "opaque-b.pdf")
    _, target_id, spec = resolve_target(db_session, sample_course.id, "learn", "学习陌生主题")
    assert target_id is None
    assert [row["material_id"] for row in spec["candidates"]] == [only.id, only.id + 1]


def test_legacy_unresolved_task_rebinds_before_start(db_session, sample_user, sample_course):
    material = _material(db_session, sample_user, sample_course, "Chap4 Network Layer.pdf")
    goal = StudyGoal(user_id=sample_user.id, title="网络", deadline=date.today(), daily_minutes=60)
    db_session.add(goal); db_session.flush()
    task = StudyTask(goal_id=goal.id, course_id=sample_course.id, title="学习网络层", task_type="learn", target_type="material", target_id=None, target_spec_json=json.dumps({"resolution_status": "unresolved"}), execution_status="pending")
    db_session.add(task); db_session.commit()
    result = start_task(db_session, task.id, sample_user.id)
    db_session.refresh(task)
    assert task.target_id == material.id and task.execution_status == "in_progress"
    assert result["route_name"] == "course-learn"
    assert result["route_params"]["material"] == material.public_id


def test_manual_target_binding_enforces_owner_course_and_readiness(db_session, sample_user, sample_course):
    goal = StudyGoal(user_id=sample_user.id, title="网络", deadline=date.today(), daily_minutes=60)
    db_session.add(goal); db_session.flush()
    task = StudyTask(goal_id=goal.id, course_id=sample_course.id, title="学习", task_type="learn", target_type="material", execution_status="pending")
    db_session.add(task); db_session.commit()
    other_course = Course(user_id=sample_user.id, name="其他课程"); db_session.add(other_course); db_session.commit()
    foreign_course_material = _material(db_session, sample_user, other_course, "x.pdf")
    with pytest.raises(NotFoundException):
        bind_task_target(db_session, task.id, sample_user.id, "material", foreign_course_material.id)
    other = User(username="bob", email="bob@test", password_hash="x"); db_session.add(other); db_session.commit()
    other_course2 = Course(user_id=other.id, name="外部"); db_session.add(other_course2); db_session.commit()
    foreign_user_material = _material(db_session, other, other_course2, "y.pdf")
    with pytest.raises(NotFoundException):
        bind_task_target(db_session, task.id, sample_user.id, "material", foreign_user_material.id)
    unready = Material(user_id=sample_user.id, course_id=sample_course.id, filename="z.pdf", file_type="pdf", file_path="z", status="processing")
    db_session.add(unready); db_session.commit()
    with pytest.raises(BusinessException):
        bind_task_target(db_session, task.id, sample_user.id, "material", unready.id)


def _quiz_task_setup(db, user, course):
    chunk_material = _material(db, user, course, "evidence.txt", "可靠证据文本")
    chunk = db.query(MaterialChunk).filter(MaterialChunk.material_id == chunk_material.id).one()
    point = KnowledgePoint(user_id=user.id, course_id=course.id, title="证据", summary="证据", status="active", generation=1, source_chunk_ids=json.dumps([chunk.id]))
    goal = StudyGoal(user_id=user.id, title="测验", deadline=date.today(), daily_minutes=60)
    db.add_all([point, goal]); db.flush()
    task = StudyTask(goal_id=goal.id, course_id=course.id, title="完成测验", task_type="quiz", target_type="quiz", target_spec_json=json.dumps({"question_count": 1, "pass_score": 60, "knowledge_point_ids": [point.id]}), execution_status="pending")
    db.add(task); db.commit()
    return task, point, chunk


def _generated_item(point, chunk):
    return {"title": "测验", "items": [{"question_type": "true_false", "question_text": "证据是否可靠", "options": [], "answer": "true", "explanation": "可靠", "difficulty": 1, "source_evidence_ids": [chunk.id], "source_evidence": [{"chunk_id": chunk.id, "quote_text": "可靠证据文本"}], "knowledge_point_id": point.id, "verification_status": "verified", "rubric": []}]}


def test_async_job_succeeds_and_only_then_binds_plan_task(db_session, sample_user, sample_course, monkeypatch):
    task, point, chunk = _quiz_task_setup(db_session, sample_user, sample_course)
    job = create_task_generation_job(db_session, task.id, sample_user.id)
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False))
    monkeypatch.setattr("app.services.quiz_creation_service.generate_quiz", lambda **kwargs: _generated_item(point, chunk))
    run_generation_job(job.id)
    db_session.expire_all()
    saved = db_session.get(QuizGenerationJob, job.id)
    task = db_session.get(StudyTask, task.id)
    assert saved.status == "succeeded" and saved.quiz_id
    assert task.target_id == saved.quiz_id and task.execution_status == "in_progress"


def test_async_job_failure_leaves_no_quiz_or_task_binding(db_session, sample_user, sample_course, monkeypatch):
    task, _, _ = _quiz_task_setup(db_session, sample_user, sample_course)
    job = create_task_generation_job(db_session, task.id, sample_user.id)
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False))
    monkeypatch.setattr("app.services.quiz_creation_service.generate_quiz", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("provider down")))
    run_generation_job(job.id)
    db_session.expire_all()
    assert db_session.get(QuizGenerationJob, job.id).status == "failed"
    assert db_session.get(StudyTask, task.id).target_id is None
    assert db_session.query(Quiz).count() == 0


def test_service_provider_calls_never_exceed_configured_limit(db_session, sample_user, sample_course, monkeypatch):
    _, point, _ = _quiz_task_setup(db_session, sample_user, sample_course)
    calls = 0
    def empty(**kwargs):
        nonlocal calls
        calls += 1
        return {"title": "x", "items": [], "drop_reasons": ["insufficient_evidence"]}
    monkeypatch.setattr("app.services.quiz_creation_service.generate_quiz", empty)
    monkeypatch.setattr(settings, "QUIZ_GENERATION_MAX_PROVIDER_CALLS", 2)
    with pytest.raises(QuizConstraintException):
        QuizCreationService.create_quiz(db_session, sample_user.id, sample_course.id, sample_course.name, [point], 1)
    assert calls == 2
    assert db_session.query(Quiz).count() == 0
