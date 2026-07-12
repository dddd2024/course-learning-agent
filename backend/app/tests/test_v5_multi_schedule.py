from datetime import date
from app.services.multi_scheduler import schedule_multi_courses

def test_multi_scheduler_persists_unscheduled_reason_shape(db_session, sample_user, sample_course, monkeypatch):
    monkeypatch.setattr("app.services.multi_scheduler.planner_generate", lambda **_: {"tasks": [{"title": "long", "estimate_minutes": 120, "priority": 1}]})
    result = schedule_multi_courses(db_session, sample_user.id, [{"course_id": sample_course.id, "deadline": date.today()}], 60)
    assert result["schedule"] == [] and result["unscheduled_tasks"][0]["reason"] == "daily_or_course_budget_exceeded"
