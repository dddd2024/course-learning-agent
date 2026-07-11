"""V3 Course Delete tests (BASE-V3-02).

These tests capture audit blockers in the course-deletion flow where
``StudyGoal`` rows are orphaned after their associated course is
deleted:

- After deleting a course, empty ``StudyGoal`` rows remain (no tasks
  left but the goal is not cleaned up).
- Multi-course goals (goals whose tasks span multiple courses) are not
  preserved — the deleted course's tasks are removed but the goal's
  progress is not recalculated.
- Goals with only one course should be deleted entirely when that
  course is deleted.

Written to FAIL on the current codebase.
"""
from datetime import date, timedelta

from app.api.deps import get_db
from app.main import app
from app.models.plan import StudyGoal, StudyTask
from app.tests.conftest import auth_headers, setup_course_with_material

TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
).encode("utf-8")

PAGE_TEXT = (
    "计算机网络课程笔记\n"
    "TCP 三次握手建立连接：SYN, SYN-ACK, ACK。\n"
    "滑动窗口协议用于流量控制。\n"
).encode("utf-8")


def _get_db_session():
    db_generator = app.dependency_overrides[get_db]()
    return next(db_generator)


def _create_multi_course_goal(db, user_id, course_a, course_b):
    """Create a StudyGoal with tasks in two different courses."""
    goal = StudyGoal(
        user_id=user_id,
        title="复习操作系统和网络",
        deadline=date.today() + timedelta(days=7),
        daily_minutes=120,
        status="active",
    )
    db.add(goal)
    db.flush()

    task_a = StudyTask(
        goal_id=goal.id,
        course_id=course_a,
        title="复习操作系统",
        task_type="review",
        estimate_minutes=60,
        priority=4,
        status="done",
    )
    task_b = StudyTask(
        goal_id=goal.id,
        course_id=course_b,
        title="复习计算机网络",
        task_type="review",
        estimate_minutes=60,
        priority=4,
        status="pending",
    )
    db.add_all([task_a, task_b])
    db.commit()
    return goal.id


def _create_single_course_goal(db, user_id, course_id):
    """Create a StudyGoal with tasks in only one course."""
    goal = StudyGoal(
        user_id=user_id,
        title="复习操作系统",
        deadline=date.today() + timedelta(days=7),
        daily_minutes=120,
        status="active",
    )
    db.add(goal)
    db.flush()

    task = StudyTask(
        goal_id=goal.id,
        course_id=course_id,
        title="复习操作系统",
        task_type="review",
        estimate_minutes=60,
        priority=4,
        status="pending",
    )
    db.add(task)
    db.commit()
    return goal.id


def test_no_empty_study_goal_after_course_delete(
    client, db_session, tmp_path, monkeypatch
) -> None:
    """After deleting a course, no empty StudyGoal should remain.

    A goal becomes "empty" when all its tasks were linked to the deleted
    course.  The V3 fix should delete such goals entirely.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    # Get the user_id from the auth headers' user.
    db = _get_db_session()
    try:
        from app.models.user import User

        user = db.query(User).filter(User.username == "alice").first()
        assert user is not None, "Test user not found"

        single_goal_id = _create_single_course_goal(db, user.id, course_id)
    finally:
        db.close()

    # Delete the course.
    resp = client.delete(f"/api/v1/courses/{course_id}", headers=headers)
    assert resp.status_code in (200, 204), resp.text

    # The single-course goal should no longer exist.
    db = _get_db_session()
    try:
        goal = db.query(StudyGoal).filter(StudyGoal.id == single_goal_id).first()
        assert goal is None, (
            f"StudyGoal {single_goal_id} should have been deleted after its "
            f"only course was removed, but it still exists"
        )
    finally:
        db.close()


def test_multi_course_goal_preserved_with_recalculated_progress(
    client, db_session, tmp_path, monkeypatch
) -> None:
    """Multi-course goal should be preserved but with recalculated progress.

    When a goal has tasks in multiple courses and one course is deleted,
    the goal should survive but its progress should reflect only the
    remaining tasks.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_a, _ = setup_course_with_material(
        client, headers, name="操作系统", content=TLB_TEXT
    )
    course_b, _ = setup_course_with_material(
        client, headers, name="计算机网络", content=PAGE_TEXT
    )

    db = _get_db_session()
    try:
        from app.models.user import User

        user = db.query(User).filter(User.username == "alice").first()
        assert user is not None

        multi_goal_id = _create_multi_course_goal(db, user.id, course_a, course_b)

        # Record initial progress: 1 of 2 tasks done = 50%.
        tasks_before = (
            db.query(StudyTask)
            .filter(StudyTask.goal_id == multi_goal_id)
            .all()
        )
        done_before = sum(1 for t in tasks_before if t.status == "done")
        total_before = len(tasks_before)
    finally:
        db.close()

    assert total_before == 2
    assert done_before == 1

    # Delete course_a (which has the "done" task).
    resp = client.delete(f"/api/v1/courses/{course_a}", headers=headers)
    assert resp.status_code in (200, 204), resp.text

    # The multi-course goal should still exist.
    db = _get_db_session()
    try:
        goal = db.query(StudyGoal).filter(StudyGoal.id == multi_goal_id).first()
        assert goal is not None, (
            f"Multi-course StudyGoal {multi_goal_id} should have been "
            f"preserved, but it was deleted"
        )

        # Remaining tasks should only be from course_b.
        remaining_tasks = (
            db.query(StudyTask)
            .filter(StudyTask.goal_id == multi_goal_id)
            .all()
        )
        assert len(remaining_tasks) == 1, (
            f"Expected 1 remaining task, got {len(remaining_tasks)}"
        )
        assert remaining_tasks[0].course_id == course_b, (
            f"Remaining task should belong to course_b ({course_b}), "
            f"got course_id={remaining_tasks[0].course_id}"
        )

        # Progress should be recalculated: the deleted course's done task
        # should NOT inflate the progress.  With 1 remaining task that is
        # pending, progress should be 0%, not 50%.
        remaining_done = sum(1 for t in remaining_tasks if t.status == "done")
        remaining_total = len(remaining_tasks)
        progress = remaining_done / remaining_total if remaining_total else 0
        assert progress == 0.0, (
            f"Expected recalculated progress=0.0 (0/1 done), got {progress} "
            f"({remaining_done}/{remaining_total})"
        )
    finally:
        db.close()


def test_single_course_goal_deleted_entirely(
    client, db_session, tmp_path, monkeypatch
) -> None:
    """Goals with only one course should be deleted when that course is deleted.

    This is a focused test for the single-course case: the goal AND all
    its tasks should be removed.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    db = _get_db_session()
    try:
        from app.models.user import User

        user = db.query(User).filter(User.username == "alice").first()
        assert user is not None

        goal_id = _create_single_course_goal(db, user.id, course_id)

        # Verify the goal exists before deletion.
        goal = db.query(StudyGoal).filter(StudyGoal.id == goal_id).first()
        assert goal is not None
    finally:
        db.close()

    # Delete the course.
    resp = client.delete(f"/api/v1/courses/{course_id}", headers=headers)
    assert resp.status_code in (200, 204), resp.text

    # Both the goal and its tasks should be gone.
    db = _get_db_session()
    try:
        goal = db.query(StudyGoal).filter(StudyGoal.id == goal_id).first()
        assert goal is None, (
            f"StudyGoal {goal_id} should have been deleted"
        )

        tasks = (
            db.query(StudyTask)
            .filter(StudyTask.goal_id == goal_id)
            .count()
        )
        assert tasks == 0, (
            f"Expected 0 tasks for deleted goal {goal_id}, got {tasks}"
        )
    finally:
        db.close()
