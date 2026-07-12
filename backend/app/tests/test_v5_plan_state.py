from datetime import date
from app.models.plan import StudyGoal, StudyTask
from app.services.plan_state_service import recompute_goal, reopen_task

def test_retry_reopens_done_goal(db_session, sample_user, sample_course):
    goal = StudyGoal(user_id=sample_user.id, title="g", deadline=date.today(), daily_minutes=30, status="done")
    db_session.add(goal); db_session.flush(); task = StudyTask(goal_id=goal.id, course_id=sample_course.id, title="t", task_type="review", status="done")
    db_session.add(task); db_session.flush(); reopen_task(db_session, task); db_session.flush(); recompute_goal(db_session, goal.id)
    assert task.status == "pending" and goal.status == "active"
