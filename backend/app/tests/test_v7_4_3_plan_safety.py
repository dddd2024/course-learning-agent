"""V7.4.3-05 uses one history authority for event-only plans."""
from __future__ import annotations

from datetime import datetime

from app.core import database as db_module
from app.models.plan import MultiCoursePlanTask, TaskExecutionEvent
from app.services.multi_plan_history_service import has_execution_history
from app.tests.test_v7_4_2_plan_safety import _make_plan_with_tasks


def test_event_only_history_blocks_delete(client):
    plan_id, headers, user_id = _make_plan_with_tasks(client, "v743_event_history", task_status="pending")
    db = db_module.SessionLocal()
    try:
        task_id = db.query(MultiCoursePlanTask.task_id).filter(
            MultiCoursePlanTask.multi_plan_id == plan_id,
            MultiCoursePlanTask.task_id.isnot(None),
        ).first()[0]
        db.add(TaskExecutionEvent(task_id=task_id, user_id=user_id, event_type="target_loaded", occurred_at=datetime.now()))
        db.commit()
        assert has_execution_history(db, plan_id)
    finally:
        db.close()
    response = client.delete(f"/api/v1/plans/multi/{plan_id}", headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "PLAN_HAS_HISTORY"
