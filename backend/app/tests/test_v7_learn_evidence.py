"""V7 evidence must represent a successful client-side target load."""
import json
from datetime import date

from app.models.material import Material
from app.models.plan import StudyGoal, StudyTask, TaskExecutionEvent
from app.services.task_execution_service import start_task, record_task_event


def _learn_task(db, user, course):
    material = Material(user_id=user.id, course_id=course.id, filename="notes.txt", file_type="txt", file_path="notes.txt", status="ready")
    db.add(material); db.flush()
    goal = StudyGoal(user_id=user.id, title="V7", deadline=date.today(), daily_minutes=30, status="active")
    db.add(goal); db.flush()
    task = StudyTask(goal_id=goal.id, course_id=course.id, title="learn", task_type="learn", estimate_minutes=10, priority=1, status="pending", target_type="material", target_id=material.id, target_spec_json=json.dumps({"material_id": material.id}), execution_status="pending")
    db.add(task); db.commit()
    return task


def test_start_does_not_record_target_loaded(db_session, sample_user, sample_course):
    sample_learn_task = _learn_task(db_session, sample_user, sample_course)
    start_task(db_session, sample_learn_task.id, sample_user.id)
    assert not db_session.query(TaskExecutionEvent).filter(
        TaskExecutionEvent.task_id == sample_learn_task.id,
        TaskExecutionEvent.event_type == "target_loaded",
    ).count()


def test_target_loaded_is_idempotent_after_start(db_session, sample_user, sample_course):
    sample_learn_task = _learn_task(db_session, sample_user, sample_course)
    start_task(db_session, sample_learn_task.id, sample_user.id)
    first = record_task_event(db_session, sample_learn_task.id, sample_user.id, "target_loaded", sample_learn_task.target_id)
    second = record_task_event(db_session, sample_learn_task.id, sample_user.id, "target_loaded", sample_learn_task.target_id)
    assert first["recorded"] is True
    assert second["recorded"] is False
