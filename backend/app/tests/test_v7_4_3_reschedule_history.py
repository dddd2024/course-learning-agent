"""V7.4.3-06 persisted reschedule-history API checks."""
from __future__ import annotations

from app.core import database as db_module
from app.models.plan import MultiPlanRescheduleDiffItem, MultiPlanRescheduleRun
from app.tests.test_v7_4_2_reschedule_diff import _auth_client, _make_course, _seed_plan_with_tasks


def test_owner_can_read_persisted_reschedule_run(client):
    user_id, headers = _auth_client(client)
    course = _make_course(user_id)
    plan = _seed_plan_with_tasks(user_id, course.id, [])
    db = db_module.SessionLocal()
    try:
        run = MultiPlanRescheduleRun(plan_id=plan.id, old_generation=1, new_generation=2, daily_minutes=60)
        db.add(run); db.flush()
        db.add(MultiPlanRescheduleDiffItem(run_id=run.id, category="created", title="新任务", course_id=course.id))
        db.commit()
        run_id = run.id
    finally:
        db.close()
    listing = client.get(f"/api/v1/plans/multi/{plan.id}/reschedule-runs", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["id"] == run_id
    detail = client.get(f"/api/v1/plans/multi/{plan.id}/reschedule-runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["items"][0]["category"] == "created"
