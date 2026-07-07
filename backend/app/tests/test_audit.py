"""Tests for the agent audit & statistics module (BE-12, AG-08).

Strict TDD: these tests are written first and fail until the
``AgentRun`` / ``AgentStep`` models, ``AgentAudit`` tool, audit
integration in chat / outline / planner endpoints, and the
``/agent-runs`` read API are implemented.

Covers:
- POST /chat creates an agent_run (run_type=course_qa)
- GET  /api/v1/agent-runs (list, user-scoped, run_type filter)
- GET  /api/v1/agent-runs/{id} (detail with steps)
- Cross-user isolation returns 404
- AgentAudit unit test (create_run / add_step / finish_run)
- OutlineAgent.generate call records an agent_run
- PlannerAgent.generate call records an agent_run
"""
from sqlalchemy.orm import Session

from app.agents.audit import AgentAudit
from app.api.deps import get_db
from app.main import app
from app.models.audit import AgentStep
from app.tests.conftest import (
    auth_headers,
    create_course,
    setup_course_with_material,
)


# Material content that mentions "快表 TLB" so keyword retrieval and
# the outline agent have meaningful chunks to work with.
TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
).encode("utf-8")


def _setup_chat(client, headers, content: bytes = TLB_TEXT) -> tuple[int, int]:
    """Create course + material + conversation; return (course_id, conv_id)."""
    course_id, _ = setup_course_with_material(client, headers, content=content)
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "TLB 答疑"},
        headers=headers,
    )
    return course_id, conv_resp.json()["id"]


def test_agent_run_created_after_chat(client, tmp_path, monkeypatch) -> None:
    """POST /chat creates exactly one agent_run with run_type=course_qa."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    chat_body = resp.json()
    # ChatResponse now surfaces the agent_run_id so the client can deep-link.
    assert chat_body.get("agent_run_id") is not None

    # GET /agent-runs lists the run for the current user.
    list_resp = client.get("/api/v1/agent-runs", headers=headers)
    assert list_resp.status_code == 200
    body = list_resp.json()
    items = body["items"] if isinstance(body, dict) else body
    assert len(items) >= 1
    course_qa_runs = [r for r in items if r["run_type"] == "course_qa"]
    assert len(course_qa_runs) >= 1
    # The chat response's run_id is among the listed runs.
    listed_ids = {r["id"] for r in items}
    assert chat_body["agent_run_id"] in listed_ids
    # The new run should be marked as success.
    new_run = next(r for r in items if r["id"] == chat_body["agent_run_id"])
    assert new_run["status"] == "success"


def test_agent_run_detail(client, tmp_path, monkeypatch) -> None:
    """GET /agent-runs/{id} returns the run with its step list."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    # Phase 2 Task B: success runs only persist steps when AGENT_TRACE_MODE
    # is "always". This test inspects step detail, so opt in explicitly.
    monkeypatch.setattr("app.core.config.settings.AGENT_TRACE_MODE", "always")

    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers)

    chat_resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    run_id = chat_resp.json()["agent_run_id"]
    assert run_id is not None

    detail_resp = client.get(f"/api/v1/agent-runs/{run_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == run_id
    assert detail["run_type"] == "course_qa"
    assert "steps" in detail
    step_names = {s["step_name"] for s in detail["steps"]}
    # course_qa should record at least retrieve + generate + validate.
    assert "retrieve" in step_names
    assert "generate" in step_names
    assert "validate" in step_names
    for step in detail["steps"]:
        assert "duration_ms" in step
        assert "status" in step


def test_agent_run_filter(client, tmp_path, monkeypatch) -> None:
    """GET /agent-runs?run_type=course_qa filters by run_type."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers)

    # Create a course_qa run via /chat.
    client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    # Create an outline run via knowledge-points/generate.
    client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )

    # Filter by run_type=course_qa — only course_qa runs appear.
    resp = client.get(
        "/api/v1/agent-runs?run_type=course_qa", headers=headers
    )
    assert resp.status_code == 200
    items = resp.json()["items"] if isinstance(resp.json(), dict) else resp.json()
    assert len(items) >= 1
    for r in items:
        assert r["run_type"] == "course_qa"

    # Filter by run_type=outline — only outline runs appear.
    resp2 = client.get(
        "/api/v1/agent-runs?run_type=outline", headers=headers
    )
    assert resp2.status_code == 200
    items2 = (
        resp2.json()["items"] if isinstance(resp2.json(), dict) else resp2.json()
    )
    assert len(items2) >= 1
    for r in items2:
        assert r["run_type"] == "outline"


def test_agent_run_isolation(client, tmp_path, monkeypatch) -> None:
    """User B cannot see user A's agent_run (list empty + detail 404)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers_a = auth_headers(client, username="alice")
    course_id, conv_id = _setup_chat(client, headers_a)
    chat_resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers_a,
    )
    run_id_a = chat_resp.json()["agent_run_id"]

    headers_b = auth_headers(client, username="bob")
    # List for user B does not include user A's run.
    list_resp = client.get("/api/v1/agent-runs", headers=headers_b)
    assert list_resp.status_code == 200
    items_b = (
        list_resp.json()["items"] if isinstance(list_resp.json(), dict) else list_resp.json()
    )
    assert all(r["id"] != run_id_a for r in items_b)

    # Detail for user B returns 404 so existence is never leaked.
    detail_resp = client.get(
        f"/api/v1/agent-runs/{run_id_a}", headers=headers_b
    )
    assert detail_resp.status_code == 404


def test_audit_records_steps(client, tmp_path, monkeypatch) -> None:
    """Unit test: AgentAudit create_run / add_step / finish_run persist rows."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    # We need a user_id; pull it from the db by reusing the test session.
    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        from app.models.user import User

        user = db.query(User).filter(User.username == "alice").first()
        assert user is not None
        user_id = user.id

        run = AgentAudit.create_run(
            db,
            user_id=user_id,
            run_type="course_qa",
            input_summary="question=什么是快表？",
            prompt_version="course_qa_v1",
            model_name="mock",
        )
        assert run.id is not None
        assert run.status == "running"
        assert run.started_at is not None
        assert run.user_id == user_id

        step = AgentAudit.add_step(
            db,
            run_id=run.id,
            step_name="retrieve",
            step_index=0,
            input_data={"query": "什么是快表？"},
            output_data={"chunk_count": 3},
            duration_ms=12,
            status="success",
        )
        assert step.id is not None
        assert step.run_id == run.id
        assert step.step_name == "retrieve"
        assert step.step_index == 0
        # input/output are stored as JSON strings.
        import json as _json

        assert _json.loads(step.input_data)["query"] == "什么是快表？"
        assert _json.loads(step.output_data)["chunk_count"] == 3

        AgentAudit.finish_run(
            db,
            run_id=run.id,
            status="success",
            output_summary="answer=快表是页表的高速缓存",
            duration_ms=42,
        )
        db.refresh(run)
        assert run.status == "success"
        assert run.finished_at is not None
        assert run.duration_ms == 42

        # The step is reachable via run.steps relationship.
        db.refresh(run)
        steps = (
            db.query(AgentStep)
            .filter(AgentStep.run_id == run.id)
            .order_by(AgentStep.step_index.asc())
            .all()
        )
        assert len(steps) == 1
        assert steps[0].step_name == "retrieve"
    finally:
        db.close()


def test_outline_run_created(client, tmp_path, monkeypatch) -> None:
    """Generating knowledge points records an outline agent_run."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    resp = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )
    assert resp.status_code == 200

    list_resp = client.get("/api/v1/agent-runs", headers=headers)
    assert list_resp.status_code == 200
    items = (
        list_resp.json()["items"] if isinstance(list_resp.json(), dict) else list_resp.json()
    )
    outline_runs = [r for r in items if r["run_type"] == "outline"]
    assert len(outline_runs) >= 1
    assert outline_runs[0]["status"] == "success"


def test_planner_run_created(client, tmp_path, monkeypatch) -> None:
    """Creating a study plan records a planner agent_run."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    create_course(client, headers, "操作系统")

    resp = client.post(
        "/api/v1/plans",
        json={
            "goal": "7天复习完操作系统",
            "courses": ["操作系统"],
            "deadline": "2026-07-30",
            "daily_minutes": 120,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    list_resp = client.get("/api/v1/agent-runs", headers=headers)
    assert list_resp.status_code == 200
    items = (
        list_resp.json()["items"] if isinstance(list_resp.json(), dict) else list_resp.json()
    )
    planner_runs = [r for r in items if r["run_type"] == "planner"]
    assert len(planner_runs) >= 1
    assert planner_runs[0]["status"] == "success"
