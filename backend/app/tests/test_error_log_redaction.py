"""Tests for sensitive-field redaction in error logs (security Task B).

The log center collects upload / parse / agent / system errors. If an
error message or technical detail contains Authorization headers, API
keys, passwords, or JWTs, those must be redacted BEFORE persistence so
the log center never becomes a secondary leak vector.

Redaction rules:
- ``Authorization: Bearer <token>``  -> ``Authorization: Bearer ***``
- ``api_key``/``apiKey``/``password``/``token`` field values -> ``***``
- ``sk-`` prefixed API key fragments -> ``sk-***``
- JWT three-segment tokens (``ey...ey...sig``) -> ``<jwt:***>``
"""
from app.core.database import get_db
from app.models.general_error_log import ErrorLog
from app.services.error_logger import log_error


def _test_db(client):
    return next(client.app.dependency_overrides[get_db]())


def test_redact_authorization_bearer(client) -> None:
    """Authorization: Bearer <token> is redacted in stored logs."""
    headers = _register_and_login(client, "alice")
    client.post(
        "/api/v1/courses",
        json={"name": "测试"},
        headers={**headers, "Authorization": "Bearer eyJabc.eyJdef.ghi"},
    )  # ignored; just to vary traffic

    db = _test_db(client)
    try:
        log_error(
            db,
            user_id=1,
            category="agent",
            title="x",
            message="Authorization: Bearer eyJabc.eyJdef.ghi failed",
            technical_detail="header=Authorization: Bearer eyJabc.eyJdef.ghi",
        )
    finally:
        db.close()

    logs = client.get("/api/v1/logs", headers=headers).json()
    last = logs["items"][0]
    assert "eyJabc" not in last["message"]
    assert "eyJabc" not in last["technical_detail"]
    assert "Bearer ***" in last["message"]
    assert "Bearer ***" in last["technical_detail"]


def test_redact_password_and_api_key_values(client) -> None:
    """password=... and api_key=... values are masked."""
    headers = _register_and_login(client, "bob")
    db = _test_db(client)
    try:
        log_error(
            db,
            user_id=1,
            category="system",
            title="x",
            message="login failed password=secret123 for admin",
            technical_detail="api_key=sk-live-1234567890abcdef rejected",
        )
    finally:
        db.close()

    logs = client.get("/api/v1/logs", headers=headers).json()
    last = logs["items"][0]
    assert "secret123" not in last["message"]
    assert "sk-live-1234567890abcdef" not in last["technical_detail"]
    assert "***" in last["message"]
    assert "***" in last["technical_detail"]


def test_redact_sk_prefixed_keys(client) -> None:
    """``sk-`` prefixed API key fragments are masked to ``sk-***``."""
    headers = _register_and_login(client, "carol")
    db = _test_db(client)
    try:
        log_error(
            db,
            user_id=1,
            category="agent",
            title="x",
            message="LLM call with sk-proj-abcdef123456 returned 401",
            technical_detail="key fragment: sk-proj-abcdef123456",
        )
    finally:
        db.close()

    logs = client.get("/api/v1/logs", headers=headers).json()
    last = logs["items"][0]
    assert "sk-proj-abcdef123456" not in last["message"]
    assert "sk-proj-abcdef123456" not in last["technical_detail"]
    assert "sk-***" in last["message"]


def test_redact_jwt_three_segment(client) -> None:
    """JWT three-segment tokens are replaced with ``<jwt:***>``."""
    headers = _register_and_login(client, "dave")
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.SflKxwRJSMeKKF2QT4fwp"
    db = _test_db(client)
    try:
        log_error(
            db,
            user_id=1,
            category="system",
            title="x",
            message=f"token={jwt} expired",
            technical_detail=jwt,
        )
    finally:
        db.close()

    logs = client.get("/api/v1/logs", headers=headers).json()
    last = logs["items"][0]
    assert jwt not in last["message"]
    assert jwt not in last["technical_detail"]
    assert "<jwt:***>" in last["technical_detail"]


# --- helpers ----------------------------------------------------------------


def _register_and_login(client, username: str) -> dict:
    client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "secret123",
            "email": f"{username}@example.com",
        },
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "secret123"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
