"""V7.4.3-07: historical knowledge-point safety boundaries."""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pytest

from app.core.exceptions import BusinessException, QuizConstraintException
from app.models.knowledge_point import KnowledgePoint
from app.models.plan import StudyGoal, StudyTask
from app.models.user import User
from app.services.quiz_creation_service import QuizCreationService
from app.services.task_execution_service import record_task_event, start_task


def _point(db, user_id, course_id, *, status="active", generation=1, stable_key="same"):
    row = KnowledgePoint(
        user_id=user_id,
        course_id=course_id,
        title=f"KP-{stable_key}-{generation}",
        summary="summary",
        importance=3,
        source_version_ids="[]",
        source_chunk_ids="[]",
        stable_key=f"{course_id}:{stable_key}",
        title_normalized=stable_key,
        status=status,
        generation=generation,
    )
    db.add(row)
    db.flush()
    return row


def test_generation_response_marks_archived_snapshot_read_only(client):
    from app.tests.test_v7_4_2_kp_history import _auth_client, _make_course, _seed_kps_with_generations

    user_id, headers = _auth_client(client, "v743_kp_readonly")
    course_id = _make_course(user_id)
    _seed_kps_with_generations(course_id, user_id)

    archived = client.get(
        f"/api/v1/courses/{course_id}/knowledge-points/generations/1", headers=headers
    )
    current = client.get(
        f"/api/v1/courses/{course_id}/knowledge-points/generations/2", headers=headers
    )
    assert archived.status_code == current.status_code == 200
    assert archived.json()["read_only"] is True
    assert archived.json()["generation_status"] == "archived"
    assert current.json()["read_only"] is False
    assert current.json()["generation_status"] == "active"


def test_quiz_rejects_cross_user_kp_before_provider_or_persistence(db_session, sample_user, sample_course):
    other = User(username="other-kp-owner", password_hash="x")
    db_session.add(other)
    db_session.flush()
    foreign = _point(db_session, other.id, sample_course.id)

    with patch("app.services.quiz_creation_service.generate_quiz") as generate:
        with pytest.raises(QuizConstraintException) as error:
            QuizCreationService.create_quiz(
                db=db_session,
                user_id=sample_user.id,
                course_id=sample_course.id,
                course_name=sample_course.name,
                knowledge_points=[foreign],
                question_count=1,
            )
    assert "knowledge_point_not_owned_or_not_active" in error.value.data["drop_reasons"]
    generate.assert_not_called()


def test_archived_review_target_rebinds_before_event_evidence(db_session, sample_user, sample_course):
    archived = _point(db_session, sample_user.id, sample_course.id, status="archived", generation=1)
    active = _point(db_session, sample_user.id, sample_course.id, status="active", generation=2)
    goal = StudyGoal(user_id=sample_user.id, title="rebind", deadline=date.today(), daily_minutes=30)
    db_session.add(goal)
    db_session.flush()
    task = StudyTask(
        goal_id=goal.id,
        course_id=sample_course.id,
        title="review",
        task_type="review",
        estimate_minutes=30,
        target_type="knowledge_point",
        target_id=archived.id,
        target_spec_json=json.dumps({"knowledge_point_id": archived.id}),
    )
    db_session.add(task)
    db_session.commit()

    started = start_task(db_session, task.id, sample_user.id)
    assert started["target_id"] == active.id
    assert record_task_event(
        db_session, task.id, sample_user.id, "target_loaded", active.id
    )["recorded"] is True
    db_session.refresh(task)
    assert task.target_id == active.id
    assert json.loads(task.target_spec_json)["rebound_from_knowledge_point_id"] == archived.id


def test_archived_review_target_without_replacement_fails_closed(db_session, sample_user, sample_course):
    archived = _point(db_session, sample_user.id, sample_course.id, status="archived")
    goal = StudyGoal(user_id=sample_user.id, title="no rebind", deadline=date.today(), daily_minutes=30)
    db_session.add(goal)
    db_session.flush()
    task = StudyTask(
        goal_id=goal.id,
        course_id=sample_course.id,
        title="review",
        task_type="review",
        estimate_minutes=30,
        target_type="knowledge_point",
        target_id=archived.id,
        target_spec_json=json.dumps({"knowledge_point_id": archived.id}),
    )
    db_session.add(task)
    db_session.commit()

    with pytest.raises(BusinessException) as error:
        start_task(db_session, task.id, sample_user.id)
    assert error.value.status_code == 422
