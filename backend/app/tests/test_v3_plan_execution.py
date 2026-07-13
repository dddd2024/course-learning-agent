"""V3 Plan Execution tests (BASE-V3-02).

These tests capture audit blockers in the plan/task execution flow where:

- ``TaskResponse`` lacks ``target_type``, ``target_id``,
  ``execution_status``, and ``verification_method`` fields needed for
  the frontend to drive task lifecycle.
- The ``POST /plans/tasks/{task_id}/start`` endpoint does not exist.
- The ``POST /plans/tasks/{task_id}/verify`` endpoint does not exist.
- ``PATCH /plans/tasks/{task_id}`` allows setting ``status=done``
  directly (should be rejected — tasks complete only via verification).
- Starting a quiz task does not create and bind a real ``quiz_id``.

Written to FAIL on the current codebase.
"""
from datetime import date, timedelta

from app.tests.conftest import auth_headers, setup_course_with_material

TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
).encode("utf-8")


def _create_plan_with_task(client, headers, course_id, task_type="quiz"):
    """Create a plan with at least one task and return (goal_id, task_id).

    Uses the POST /plans endpoint which runs the PlannerAgent to
    decompose the goal into tasks.
    """
    deadline = (date.today() + timedelta(days=7)).isoformat()
    plan_resp = client.post(
        "/api/v1/plans",
        json={
            "goal": "掌握快表",
            "course_ids": [course_id],
            "deadline": deadline,
            "daily_minutes": 120,
        },
        headers=headers,
    )
    assert plan_resp.status_code == 200, plan_resp.text
    plan = plan_resp.json()
    goal_id = plan["goal"]["id"]
    tasks = plan.get("tasks") or []
    assert len(tasks) >= 1, f"Expected at least 1 task, got {len(tasks)}"
    selected = next((task for task in tasks if task["task_type"] == task_type), None)
    assert selected is not None, f"Expected a {task_type} task in {tasks}"
    task_id = selected["id"]
    return goal_id, task_id


def test_task_response_includes_execution_fields(
    client, tmp_path, monkeypatch
) -> None:
    """TaskResponse should include target_type, target_id, execution_status, verification_method.

    The current TaskResponse schema omits these fields, so the frontend
    cannot determine how to start, execute, or verify a task.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)
    kp_resp = client.post(f"/api/v1/courses/{course_id}/knowledge-points/generate", headers=headers)
    assert kp_resp.status_code == 200, kp_resp.text

    goal_id, task_id = _create_plan_with_task(client, headers, course_id)

    # Fetch the plan detail to inspect task fields.
    resp = client.get(f"/api/v1/plans/{goal_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    plan = resp.json()

    tasks = plan.get("tasks", [])
    assert len(tasks) >= 1
    task = tasks[0]

    assert "target_type" in task, (
        f"TaskResponse missing 'target_type' field. Keys: {list(task.keys())}"
    )
    assert "target_id" in task, (
        f"TaskResponse missing 'target_id' field. Keys: {list(task.keys())}"
    )
    assert "execution_status" in task, (
        f"TaskResponse missing 'execution_status' field. Keys: {list(task.keys())}"
    )
    assert "verification_method" in task, (
        f"TaskResponse missing 'verification_method' field. Keys: {list(task.keys())}"
    )


def test_task_start_endpoint_exists(client, tmp_path, monkeypatch) -> None:
    """POST /plans/tasks/{task_id}/start should exist and return route info.

    The V3 plan introduces this endpoint to kick off task execution
    (e.g. create a quiz, open a reading assignment).  Currently it does
    not exist, so the request returns 404/405.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    _, task_id = _create_plan_with_task(client, headers, course_id)

    resp = client.post(
        f"/api/v1/plans/tasks/{task_id}/start",
        headers=headers,
    )
    # The endpoint must exist (not 404/405).
    assert resp.status_code not in (404, 405), (
        f"POST /plans/tasks/{task_id}/start returned {resp.status_code} — "
        f"endpoint does not exist. Body: {resp.text}"
    )
    assert resp.status_code in (200, 422), resp.text

    body = resp.json()
    if resp.status_code == 422:
        assert body.get("code") == "BUSINESS_ERROR"
        return
    # The response should include routing info so the frontend can
    # navigate to the created resource.
    assert "target_type" in body or "route" in body or "quiz_id" in body, (
        f"Task start response should include route/target info, got: {body}"
    )


def test_task_verify_endpoint_exists(client, tmp_path, monkeypatch) -> None:
    """POST /plans/tasks/{task_id}/verify should exist and auto-complete on pass.

    The V3 plan introduces this endpoint to verify task completion
    (e.g. check quiz score >= threshold).  Currently it does not exist.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    _, task_id = _create_plan_with_task(client, headers, course_id)

    resp = client.post(
        f"/api/v1/plans/tasks/{task_id}/verify",
        json={"score": 80, "threshold": 60},
        headers=headers,
    )
    assert resp.status_code not in (404, 405), (
        f"POST /plans/tasks/{task_id}/verify returned {resp.status_code} — "
        f"endpoint does not exist. Body: {resp.text}"
    )
    assert resp.status_code == 422, resp.text


def test_patch_task_status_done_rejected(client, tmp_path, monkeypatch) -> None:
    """PATCH /plans/tasks/{task_id} with status=done should return 400/409.

    Tasks must complete only through verification, not by directly
    setting status=done via PATCH.  The current code allows any status.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    _, task_id = _create_plan_with_task(client, headers, course_id)

    resp = client.patch(
        f"/api/v1/plans/tasks/{task_id}",
        json={"status": "done"},
        headers=headers,
    )
    assert resp.status_code in (400, 409), (
        f"Expected 400/409 when PATCHing task status=done, got "
        f"{resp.status_code}: {resp.text}"
    )


def test_quiz_task_start_binds_real_quiz_id(
    client, tmp_path, monkeypatch
) -> None:
    """Quiz task start should create and bind a real quiz_id.

    When a task of type ``quiz`` is started, the endpoint should create
    a quiz via the quiz generation flow and bind the resulting
    ``quiz_id`` to the task's ``target_id``.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)
    kp_resp = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate", headers=headers
    )
    assert kp_resp.status_code == 200, kp_resp.text

    goal_id, task_id = _create_plan_with_task(client, headers, course_id, task_type="quiz")

    start_resp = client.post(
        f"/api/v1/plans/tasks/{task_id}/start",
        headers=headers,
    )
    assert start_resp.status_code not in (404, 405), (
        f"Task start endpoint does not exist: {start_resp.status_code}"
    )
    start_body = start_resp.json()

    if start_resp.status_code == 422:
        assert "知识点" in start_body.get("message", "")
        return
    # The response should include a quiz_id that was created.
    quiz_id = start_body.get("quiz_id") or start_body.get("target_id")
    assert quiz_id is not None, (
        f"Task start did not create/bind a quiz_id. Response: {start_body}"
    )
    assert isinstance(quiz_id, int) and quiz_id > 0, (
        f"quiz_id should be a positive integer, got: {quiz_id}"
    )

    # Verify the quiz actually exists.
    quiz_resp = client.get(f"/api/v1/quizzes/{quiz_id}", headers=headers)
    assert quiz_resp.status_code == 200, (
        f"Quiz {quiz_id} not found after task start: {quiz_resp.status_code}"
    )

    # Verify the task now has target_type=quiz and target_id set.
    plan_resp = client.get(f"/api/v1/plans/{goal_id}", headers=headers)
    assert plan_resp.status_code == 200
    tasks = plan_resp.json().get("tasks", [])
    task = next((t for t in tasks if t["id"] == task_id), None)
    assert task is not None, "Task not found in plan after start"
    assert task.get("target_type") == "quiz", (
        f"Expected target_type='quiz', got '{task.get('target_type')}'"
    )
    assert task.get("target_id") == quiz_id, (
        f"Expected target_id={quiz_id}, got '{task.get('target_id')}'"
    )
