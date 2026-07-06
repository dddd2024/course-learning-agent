"""Enhanced tests for the agent audit module (Task 6 — AgentAudit 增强).

Strict TDD: these tests are written first and fail until the
``AgentRun`` model gains ``provider`` / ``config_id`` columns, the
``AgentAudit.create_run`` helper accepts those parameters, and the
``AgentRunResponse`` schema surfaces them.

Covers:
- create_run persists ``provider`` (mock / real / user)
- create_run persists ``config_id`` (FK to user_llm_configs.id)
- ``provider`` defaults to ``None`` when not supplied
- ``AgentRunResponse`` serialises ``provider`` / ``config_id``
- No ``api_key`` is ever written into the audit record
- Existing audit-flow patterns (create_run / add_step / finish_run)
  still work after the new fields are introduced.
"""
import json
import inspect

from sqlalchemy.orm import Session

from app.agents.audit import AgentAudit
from app.api.deps import get_db
from app.main import app
from app.models.audit import AgentRun
from app.models.user import User
from app.schemas.audit import AgentRunResponse
from app.tests.conftest import auth_headers


def _get_test_db_and_user(client, username: str = "alice") -> tuple[Session, int]:
    """Return the test db session and the user id for ``username``.

    Mirrors the pattern used in ``test_audit.py::test_audit_records_steps``
    so we can call ``AgentAudit`` helpers directly against the same
    in-memory SQLite database the TestClient uses.
    """
    headers = auth_headers(client, username=username)
    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    user = db.query(User).filter(User.username == username).first()
    assert user is not None
    return db, user.id, headers


def test_agent_run_has_provider_field(client) -> None:
    """create_run with provider='user' persists provider='user'."""
    db, user_id, _ = _get_test_db_and_user(client)
    try:
        run = AgentAudit.create_run(
            db,
            user_id=user_id,
            run_type="course_qa",
            input_summary={"question": "什么是快表？"},
            model_name="mock",
            provider="user",
        )
        db.commit()
        db.refresh(run)
        assert run.provider == "user"

        # Re-fetch from the DB to be sure the column is persisted.
        fetched = db.query(AgentRun).filter(AgentRun.id == run.id).first()
        assert fetched is not None
        assert fetched.provider == "user"
    finally:
        db.close()


def test_agent_run_has_config_id_field(client) -> None:
    """create_run with config_id=5 persists config_id=5."""
    db, user_id, _ = _get_test_db_and_user(client)
    try:
        run = AgentAudit.create_run(
            db,
            user_id=user_id,
            run_type="course_qa",
            input_summary={"question": "什么是快表？"},
            model_name="mock",
            provider="user",
            config_id=5,
        )
        db.commit()
        db.refresh(run)
        assert run.config_id == 5

        fetched = db.query(AgentRun).filter(AgentRun.id == run.id).first()
        assert fetched is not None
        assert fetched.config_id == 5
    finally:
        db.close()


def test_agent_run_provider_default_none(client) -> None:
    """create_run without provider / config_id leaves both as None."""
    db, user_id, _ = _get_test_db_and_user(client)
    try:
        run = AgentAudit.create_run(
            db,
            user_id=user_id,
            run_type="course_qa",
            input_summary={"question": "什么是快表？"},
            model_name="mock",
        )
        db.commit()
        db.refresh(run)
        assert run.provider is None
        assert run.config_id is None

        fetched = db.query(AgentRun).filter(AgentRun.id == run.id).first()
        assert fetched is not None
        assert fetched.provider is None
        assert fetched.config_id is None
    finally:
        db.close()


def test_agent_run_response_schema_includes_provider(client) -> None:
    """AgentRunResponse surfaces provider and config_id fields."""
    db, user_id, _ = _get_test_db_and_user(client)
    try:
        run = AgentAudit.create_run(
            db,
            user_id=user_id,
            run_type="course_qa",
            input_summary={"question": "什么是快表？"},
            model_name="mock",
            provider="real",
            config_id=7,
        )
        db.commit()
        db.refresh(run)

        resp = AgentRunResponse.model_validate(run)
        assert resp.provider == "real"
        assert resp.config_id == 7

        # The serialised dict also carries the new fields so the API
        # response exposes them to clients.
        data = resp.model_dump()
        assert data["provider"] == "real"
        assert data["config_id"] == 7
    finally:
        db.close()


def test_audit_no_api_key_in_record(client) -> None:
    """create_run never persists an api_key anywhere in the audit record.

    The audit trail is meant to be safe to inspect / share, so the
    helper must not accept an ``api_key`` argument and must not write
    any api_key-ish string into ``input_summary`` / ``output_summary``.
    """
    # 1. create_run signature must NOT accept an ``api_key`` parameter.
    sig = inspect.signature(AgentAudit.create_run)
    assert "api_key" not in sig.parameters

    # 2. AgentRun must NOT have an api_key-like column.
    api_key_cols = [
        col_name
        for col_name in AgentRun.__table__.columns.keys()
        if "api_key" in col_name.lower() or "apikey" in col_name.lower()
    ]
    assert api_key_cols == []

    db, user_id, _ = _get_test_db_and_user(client)
    try:
        # 3. Pass a normal input_summary; ensure nothing api_key-shaped
        #    ends up stored in the audit row.
        run = AgentAudit.create_run(
            db,
            user_id=user_id,
            run_type="course_qa",
            input_summary={"question": "什么是快表？", "course_id": 1},
            model_name="mock",
            provider="user",
            config_id=9,
        )
        AgentAudit.finish_run(
            db,
            run_id=run.id,
            status="success",
            output_summary={"answer": "快表是页表的高速缓存", "citation_count": 2},
        )
        db.commit()
        db.refresh(run)

        # 4. No text column should mention api_key.
        text_fields = [
            run.input_summary,
            run.output_summary,
            run.error_message,
            run.model_name,
            run.run_type,
            run.status,
            run.prompt_version,
        ]
        for value in text_fields:
            if value is None:
                continue
            lowered = str(value).lower()
            assert "api_key" not in lowered
            assert "apikey" not in lowered
            # The raw key prefix should never appear either.
            assert "sk-" not in lowered
    finally:
        db.close()


def test_existing_audit_tests_still_pass(client) -> None:
    """Backward-compat smoke test: the create/add_step/finish flow that
    ``test_audit.py`` relies on still works after the new fields are
    added.

    This mirrors the core of ``test_audit.py::test_audit_records_steps``
    so a regression in the existing flow is caught here too.
    """
    db, user_id, _ = _get_test_db_and_user(client)
    try:
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
        # New fields default to None when not supplied.
        assert run.provider is None
        assert run.config_id is None

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
        assert json.loads(step.input_data)["query"] == "什么是快表？"
        assert json.loads(step.output_data)["chunk_count"] == 3

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
    finally:
        db.close()
