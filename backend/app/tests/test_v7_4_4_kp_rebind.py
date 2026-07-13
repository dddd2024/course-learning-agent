"""V7.4.4-06 stale archived-KP route contract."""
from __future__ import annotations

import json
from datetime import date

from app.models.plan import StudyGoal, StudyTask
from app.services.task_execution_service import record_task_event, start_task
from app.tests.test_v7_4_3_kp_readonly import _point


def test_stale_archived_target_is_accepted_and_reported_as_effective_target(
    db_session, sample_user, sample_course
):
    archived = _point(db_session, sample_user.id, sample_course.id, status="archived", generation=1)
    active = _point(db_session, sample_user.id, sample_course.id, status="active", generation=2)
    goal = StudyGoal(user_id=sample_user.id, title="rebind", deadline=date.today(), daily_minutes=30)
    db_session.add(goal)
    db_session.flush()
    task = StudyTask(
        goal_id=goal.id, course_id=sample_course.id, title="review", task_type="review",
        estimate_minutes=30, target_type="knowledge_point", target_id=archived.id,
        target_spec_json=json.dumps({"knowledge_point_id": archived.id}),
    )
    db_session.add(task)
    db_session.commit()

    started = start_task(db_session, task.id, sample_user.id)
    assert started["effective_target_id"] == active.id
    assert started["rebound_from_target_id"] == archived.id
    event = record_task_event(
        db_session, task.id, sample_user.id, "target_loaded", archived.id
    )
    assert event == {
        "recorded": True, "event_type": "target_loaded",
        "effective_target_id": active.id, "rebound_from_target_id": archived.id,
    }
