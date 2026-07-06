"""Tests for the user authentication module (registration, login, JWT).

These tests drive the TDD implementation of:
- POST /api/v1/auth/register
- POST /api/v1/auth/login
- GET  /api/v1/auth/me  (protected)
"""


def test_register_success(client) -> None:
    """POST /api/v1/auth/register returns 201 with user_id and username."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice",
            "password": "secret123",
            "email": "alice@example.com",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert "user_id" in body


def test_register_duplicate(client) -> None:
    """Registering an existing username returns 400 with code USERNAME_EXISTS."""
    payload = {
        "username": "bob",
        "password": "secret123",
        "email": "bob@example.com",
    }
    first = client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    response = client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 400
    assert response.json()["code"] == "USERNAME_EXISTS"


def test_register_short_password(client) -> None:
    """Passwords shorter than 6 characters are rejected with 422 or 400."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "carol",
            "password": "12345",
            "email": "carol@example.com",
        },
    )

    assert response.status_code in (400, 422)


def test_login_success(client) -> None:
    """POST /api/v1/auth/login returns 200 with an access_token."""
    client.post(
        "/api/v1/auth/register",
        json={
            "username": "dave",
            "password": "secret123",
            "email": "dave@example.com",
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "dave", "password": "secret123"},
    )

    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_wrong_password(client) -> None:
    """Wrong password returns 401."""
    client.post(
        "/api/v1/auth/register",
        json={
            "username": "eve",
            "password": "secret123",
            "email": "eve@example.com",
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "eve", "password": "WRONG"},
    )

    assert response.status_code == 401


def test_protected_endpoint_without_token(client) -> None:
    """Accessing a protected endpoint without a token returns 401."""
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_protected_endpoint_with_token(client) -> None:
    """Accessing a protected endpoint with a valid token returns 200."""
    client.post(
        "/api/v1/auth/register",
        json={
            "username": "frank",
            "password": "secret123",
            "email": "frank@example.com",
        },
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "frank", "password": "secret123"},
    )
    token = login_resp.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["username"] == "frank"
