"""V7.4.4-05 behavior tests for stable plan-task identities."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from app.core import database as db_module
from app.models.plan import MultiCoursePlan, MultiCoursePlanTask, MultiPlanRescheduleDiffItem, MultiPlanRescheduleRun, StudyTask, Todo
from app.tests.test_v7_4_multi_plan_lifecycle import _auth_client, _make_course, _seed_multi_plan


def _schedule(course):
    return {
        "schedule": [{
            "course_id": course.id, "course_name": course.name,
            "title": "学习第一章", "task_type": "learn", "estimate_minutes": 60,
            "priority": 3, "scheduled_date": date(2026, 7, 20), "acceptance": "完成",
        }],
        "overflow_warnings": [],
        "unscheduled_tasks": [{
            "course_id": course.id, "title": "复习第二章", "task_type": "review",
            "estimate_minutes": 30, "reason": "超出截止日期", "depends_on": [],
            "deadline": date(2026, 7, 21), "suggestion": "延长学习期限",
        }],
    }


def test_reschedule_persists_nonempty_key_for_unscheduled_item(client):
    user_id, headers = _auth_client(client)
    course = _make_course(user_id, "V744 stable key")
    plan = _seed_multi_plan(user_id, course.id)
    with patch("app.api.v1.endpoints.plans.schedule_multi_courses", return_value=_schedule(course)):
        response = client.post(
            f"/api/v1/plans/multi/{plan.id}/reschedule",
            json={"daily_minutes": 90}, headers=headers,
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["diff"]["unscheduled"]
    assert all(item["stable_task_key"] for item in body["diff"]["unscheduled"])
    db = db_module.SessionLocal()
    try:
        entries = db.query(MultiCoursePlanTask).filter(
            MultiCoursePlanTask.multi_plan_id == plan.id,
            MultiCoursePlanTask.task_id.is_(None),
            MultiCoursePlanTask.generation == 2,
        ).all()
        assert entries and all(entry.stable_task_key for entry in entries)
        assert all(entry.task_type_snapshot for entry in entries)
    finally:
        db.close()


def test_three_reschedules_diff_reads_only_immediately_previous_generation(client):
    user_id, headers = _auth_client(client)
    course = _make_course(user_id, "V744 generations")
    plan = _seed_multi_plan(user_id, course.id)
    with patch("app.api.v1.endpoints.plans.schedule_multi_courses", return_value=_schedule(course)):
        for _ in range(3):
            response = client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 90}, headers=headers,
            )
            assert response.status_code == 200, response.text
    db = db_module.SessionLocal()
    try:
        current = db.query(MultiCoursePlan).filter_by(id=plan.id).first()
        latest = db.query(MultiPlanRescheduleRun).filter_by(plan_id=plan.id).order_by(
            MultiPlanRescheduleRun.id.desc()
        ).first()
        entries = db.query(MultiPlanRescheduleDiffItem).filter_by(run_id=latest.id).all()
        assert current.generation_version == 4
        assert latest.old_generation == 3 and latest.new_generation == 4
        assert all(
            entry.old_generation in (None, latest.old_generation)
            for entry in entries
        )
    finally:
        db.close()


def test_reschedule_run_detail_is_owner_scoped(client):
    user_id, headers = _auth_client(client)
    course = _make_course(user_id, "V744 owner")
    plan = _seed_multi_plan(user_id, course.id)
    with patch("app.api.v1.endpoints.plans.schedule_multi_courses", return_value=_schedule(course)):
        response = client.post(
            f"/api/v1/plans/multi/{plan.id}/reschedule",
            json={"daily_minutes": 90}, headers=headers,
        )
    run_id = db_module.SessionLocal().query(MultiPlanRescheduleRun).filter_by(plan_id=plan.id).first().id
    _, other_headers = _auth_client(client)
    response = client.get(
        f"/api/v1/plans/multi/{plan.id}/reschedule-runs/{run_id}", headers=other_headers
    )
    assert response.status_code == 404


@pytest.mark.parametrize("stage", ["new_tasks_created", "diff_construct", "diff_write"])
def test_reschedule_failure_rolls_back_every_persisted_surface(client, monkeypatch, stage):
    user_id, headers = _auth_client(client)
    course = _make_course(user_id, f"V744 rollback {stage}")
    plan = _seed_multi_plan(user_id, course.id)
    db = db_module.SessionLocal()
    try:
        before = {
            "generation": db.query(MultiCoursePlan).filter_by(id=plan.id).first().generation_version,
            "tasks": db.query(StudyTask).count(),
            "todos": db.query(Todo).count(),
            "plan_tasks": db.query(MultiCoursePlanTask).filter_by(multi_plan_id=plan.id).count(),
            "runs": db.query(MultiPlanRescheduleRun).filter_by(plan_id=plan.id).count(),
            "diffs": db.query(MultiPlanRescheduleDiffItem).count(),
        }
    finally:
        db.close()

    def fail_at(current_stage: str):
        if current_stage == stage:
            raise RuntimeError(f"injected {stage}")

    monkeypatch.setattr("app.api.v1.endpoints.plans._reschedule_stage", fail_at)
    with patch("app.api.v1.endpoints.plans.schedule_multi_courses", return_value=_schedule(course)):
        with pytest.raises(RuntimeError, match=stage):
            client.post(
                f"/api/v1/plans/multi/{plan.id}/reschedule",
                json={"daily_minutes": 90}, headers=headers,
            )

    db = db_module.SessionLocal()
    try:
        after = {
            "generation": db.query(MultiCoursePlan).filter_by(id=plan.id).first().generation_version,
            "tasks": db.query(StudyTask).count(),
            "todos": db.query(Todo).count(),
            "plan_tasks": db.query(MultiCoursePlanTask).filter_by(multi_plan_id=plan.id).count(),
            "runs": db.query(MultiPlanRescheduleRun).filter_by(plan_id=plan.id).count(),
            "diffs": db.query(MultiPlanRescheduleDiffItem).count(),
        }
    finally:
        db.close()
    assert after == before
