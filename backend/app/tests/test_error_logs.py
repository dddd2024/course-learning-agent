"""Tests for agent error logs (Phase 2 Task E)."""
from app.core.database import get_db
from app.models.error_log import AgentErrorLog
from app.models.user import User
from app.tests.conftest import auth_headers


def _get_test_db(client):
    """Return the test session bound to the client's in-memory DB."""
    return next(app_dependency() for app_dependency in [client.app.dependency_overrides[get_db]])


def test_error_logs_empty(client) -> None:
    """A new user has no error logs."""
    headers = auth_headers(client, username="alice")
    resp = client.get("/api/v1/agent-error-logs", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_error_logs_unauthenticated(client) -> None:
    """Unauthenticated request returns 401."""
    resp = client.get("/api/v1/agent-error-logs")
    assert resp.status_code == 401


def test_error_logs_isolation(client) -> None:
    """User B cannot see user A's error logs."""
    headers_a = auth_headers(client, username="alice")
    gen = client.app.dependency_overrides[get_db]
    db = next(gen())
    try:
        user = db.query(User).filter(User.username == "alice").first()
        db.add(
            AgentErrorLog(
                user_id=user.id,
                step="generate",
                provider="mock",
                error_type="TimeoutError",
                error_message="model timeout",
            )
        )
        db.commit()
    finally:
        db.close()

    # User A sees 1 log
    resp_a = client.get("/api/v1/agent-error-logs", headers=headers_a)
    assert resp_a.status_code == 200
    assert resp_a.json()["total"] == 1

    # User B sees 0 logs
    headers_b = auth_headers(client, username="bob")
    resp_b = client.get("/api/v1/agent-error-logs", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["total"] == 0


def test_error_logs_pagination(client) -> None:
    """limit/offset pagination works."""
    headers = auth_headers(client, username="alice")
    gen = client.app.dependency_overrides[get_db]
    db = next(gen())
    try:
        user = db.query(User).filter(User.username == "alice").first()
        for i in range(5):
            db.add(
                AgentErrorLog(
                    user_id=user.id,
                    step="generate",
                    error_type="TimeoutError",
                    error_message=f"error {i}",
                )
            )
        db.commit()
    finally:
        db.close()

    resp = client.get(
        "/api/v1/agent-error-logs?limit=2&offset=0", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
