import json
from datetime import date

import pytest

from app.core.exceptions import BusinessException
from app.models.plan import StudyGoal, StudyTask
from app.services.task_execution_service import record_task_event


def test_review_target_loaded_rejects_another_knowledge_point(db_session, sample_user, sample_course):
    goal = StudyGoal(user_id=sample_user.id, title="g", deadline=date(2026, 12, 1), daily_minutes=30)
    db_session.add(goal); db_session.flush()
    task = StudyTask(goal_id=goal.id, course_id=sample_course.id, title="r", task_type="review", target_type="knowledge_point", target_id=41,
                     target_spec_json=json.dumps({"knowledge_point_id": 41}))
    db_session.add(task); db_session.commit()
    with pytest.raises(BusinessException) as error:
        record_task_event(db_session, task.id, sample_user.id, "target_loaded", 42)
    assert error.value.status_code == 409
    assert record_task_event(db_session, task.id, sample_user.id, "target_loaded", 41)["recorded"] is True
