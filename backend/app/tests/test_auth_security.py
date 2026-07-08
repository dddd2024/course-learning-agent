"""Tests for auth security hardening (security Task C/D).

Covers:
- ACCESS_TOKEN_EXPIRE_MINUTES default lowered from 10080 to 480.
- An expired token is rejected (401) by protected endpoints.
- login returns a bearer token.
- Email masking: UserResponse exposes email_masked without leaking
  the full address (security Task C1).
"""
from datetime import timedelta

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.schemas.user import UserResponse
from app.tests.conftest import auth_headers, create_course


def test_default_token_expiry_lowered() -> None:
    """Default ACCESS_TOKEN_EXPIRE_MINUTES is 480 (8h), not 10080 (7d)."""
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 480


def test_expired_token_rejected(client, monkeypatch) -> None:
    """An expired JWT is rejected by a protected endpoint (401)."""
    # Forge a token that is already expired.
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    expired_token = create_access_token({"sub": "1"})
    # Restore a positive expiry so other code paths are unaffected.
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 480)

    resp = client.get(
        "/api/v1/courses",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401


def test_login_returns_bearer_token(client) -> None:
    """POST /auth/login returns {access_token, token_type=bearer}."""
    client.post(
        "/api/v1/auth/register",
        json={"username": "sec", "password": "secret123", "email": "s@x.com"},
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "sec", "password": "secret123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    # The token must decode successfully.
    payload = decode_access_token(body["access_token"])
    assert "exp" in payload


def test_me_returns_email_masked(client) -> None:
    """GET /auth/me returns a masked email, not the full address."""
    client.post(
        "/api/v1/auth/register",
        json={
            "username": "mailuser",
            "password": "secret123",
            "email": "alice@example.com",
        },
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "mailuser", "password": "secret123"},
    )
    token = resp.json()["access_token"]
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    body = me.json()
    assert "email_masked" in body
    masked = body["email_masked"]
    assert masked is not None
    # The full plaintext email must not appear in the masked form.
    assert "alice@example.com" != masked
    assert "@" in masked
    assert "alice" not in masked


def test_register_returns_email_masked(client) -> None:
    """POST /auth/register returns a masked email."""
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "username": "reguser",
            "password": "secret123",
            "email": "bob@example.com",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "email_masked" in body
    assert body["email_masked"] != "bob@example.com"
    assert "bob" not in body["email_masked"]


def test_email_masking_helper() -> None:
    """The masking helper produces a***@e***.com style output."""
    from app.schemas.user import mask_email

    assert mask_email("alice@example.com") == "a***@e***.com"
    assert mask_email("b@x.com") == "b***@x***.com"
    assert mask_email(None) is None
    assert mask_email("") == ""


def test_security_status_endpoint(client, monkeypatch) -> None:
    """GET /auth/security-status returns the security posture for display."""
    client.post(
        "/api/v1/auth/register",
        json={"username": "secstat", "password": "secret123", "email": "s@x.com"},
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "secstat", "password": "secret123"},
    )
    token = resp.json()["access_token"]

    status = client.get(
        "/api/v1/auth/security-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status.status_code == 200
    body = status.json()
    assert body["password_storage"] == "bcrypt_hash"
    assert body["api_key_storage"] == "fernet_encrypted"
    assert body["token_expiry_minutes"] == 480
    assert body["environment"] == "development"
    assert "using_default_secret" in body
    # Development + default secret should flag the risk.
    assert body["using_default_secret"] is True


def test_security_status_production_no_default_secret_flag_leak(
    client, monkeypatch
) -> None:
    """In production the default-secret flag must not be exposed."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "LLM_CONFIG_SECRET_KEY", "a-valid-fernet-key-1234567890")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "a-strong-prod-secret")
    client.post(
        "/api/v1/auth/register",
        json={"username": "prodstat", "password": "secret123", "email": "p@x.com"},
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "prodstat", "password": "secret123"},
    )
    token = resp.json()["access_token"]

    status = client.get(
        "/api/v1/auth/security-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status.status_code == 200
    body = status.json()
    assert body["environment"] == "production"
    # using_default_secret is only surfaced in development; in production
    # the backend refuses to start with a default secret, so the flag is
    # always False here (no leak of internal key state).
    assert body["using_default_secret"] is False
