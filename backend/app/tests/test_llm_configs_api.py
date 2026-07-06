"""Tests for the LLM config API endpoints (Task 3).

Strict TDD: these tests are written first and fail until the
``llm_configs`` router is implemented and registered.

Covers:
- POST   /api/v1/llm-configs         (create, api_key masked, no plaintext)
- GET    /api/v1/llm-configs         (list, user-scoped)
- GET    /api/v1/llm-configs/active  (active config or config=null)
- PUT    /api/v1/llm-configs/{id}    (update, api_key re-encrypted)
- DELETE /api/v1/llm-configs/{id}    (delete)
- POST   /api/v1/llm-configs/{id}/enable (mutual exclusivity)
- POST   /api/v1/llm-configs/{id}/test    (test_connection, mocked)
- Cross-user isolation (404)
- No response leaks the plaintext api_key
"""
from unittest.mock import patch

from app.tests.conftest import auth_headers

PLAINTEXT_KEY = "sk-abcdef1234567890"

CREATE_PAYLOAD = {
    "provider": "openai",
    "name": "my-openai",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "api_key": PLAINTEXT_KEY,
    "temperature": 0.2,
    "max_tokens": 2000,
    "timeout_seconds": 60,
}


def _create_config(client, headers, payload=None):
    """Create a config and return the response body."""
    resp = client.post(
        "/api/v1/llm-configs",
        json=payload or CREATE_PAYLOAD,
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# POST /llm-configs
# ---------------------------------------------------------------------------


def test_create_config(client) -> None:
    """POST /llm-configs returns 201 with api_key_masked, no plaintext."""
    headers = auth_headers(client, username="alice")
    body = _create_config(client, headers)

    assert body["id"] is not None
    assert body["provider"] == "openai"
    assert body["name"] == "my-openai"
    assert body["model"] == "gpt-4o-mini"
    # api_key_masked must be present, never the plaintext or encrypted form.
    assert "api_key_masked" in body
    assert PLAINTEXT_KEY not in body["api_key_masked"]
    assert PLAINTEXT_KEY not in str(body)
    assert "api_key_encrypted" not in body


# ---------------------------------------------------------------------------
# GET /llm-configs
# ---------------------------------------------------------------------------


def test_list_configs(client) -> None:
    """GET /llm-configs returns the current user's configs as a list."""
    headers = auth_headers(client, username="alice")
    _create_config(client, headers, payload={**CREATE_PAYLOAD, "name": "a"})
    _create_config(client, headers, payload={**CREATE_PAYLOAD, "name": "b"})

    resp = client.get("/api/v1/llm-configs", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    items = body["items"] if isinstance(body, dict) else body
    assert len(items) == 2
    for item in items:
        assert PLAINTEXT_KEY not in str(item)
        assert "api_key_encrypted" not in item


# ---------------------------------------------------------------------------
# GET /llm-configs/active
# ---------------------------------------------------------------------------


def test_get_active_config(client) -> None:
    """GET /llm-configs/active returns the enabled default config."""
    headers = auth_headers(client, username="alice")
    body = _create_config(client, headers)
    config_id = body["id"]

    enable_resp = client.post(
        f"/api/v1/llm-configs/{config_id}/enable", headers=headers
    )
    assert enable_resp.status_code == 200

    resp = client.get("/api/v1/llm-configs/active", headers=headers)
    assert resp.status_code == 200
    active = resp.json()
    assert active["config"] is not None
    assert active["config"]["id"] == config_id
    assert active["config"]["is_default"] is True
    assert PLAINTEXT_KEY not in str(active)


def test_get_active_config_none(client) -> None:
    """GET /llm-configs/active returns config=null when none is default."""
    headers = auth_headers(client, username="alice")
    _create_config(client, headers)

    resp = client.get("/api/v1/llm-configs/active", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["config"] is None


# ---------------------------------------------------------------------------
# PUT /llm-configs/{id}
# ---------------------------------------------------------------------------


def test_update_config(client) -> None:
    """PUT /llm-configs/{id} updates non-secret fields."""
    headers = auth_headers(client, username="alice")
    body = _create_config(client, headers)
    config_id = body["id"]

    resp = client.put(
        f"/api/v1/llm-configs/{config_id}",
        json={"name": "renamed", "model": "gpt-4o"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["name"] == "renamed"
    assert updated["model"] == "gpt-4o"
    assert PLAINTEXT_KEY not in str(updated)


def test_update_config_api_key(client) -> None:
    """PUT /llm-configs/{id} with a new api_key re-encrypts it."""
    headers = auth_headers(client, username="alice")
    body = _create_config(client, headers)
    config_id = body["id"]
    original_masked = body["api_key_masked"]

    new_key = "sk-newkey-999999888888"
    resp = client.put(
        f"/api/v1/llm-configs/{config_id}",
        json={"api_key": new_key},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    # The masked form must reflect the new key (different prefix).
    assert updated["api_key_masked"] != original_masked
    # Neither old nor new plaintext may leak.
    assert PLAINTEXT_KEY not in str(updated)
    assert new_key not in str(updated)


# ---------------------------------------------------------------------------
# DELETE /llm-configs/{id}
# ---------------------------------------------------------------------------


def test_delete_config(client) -> None:
    """DELETE /llm-configs/{id} removes the config (subsequent 404)."""
    headers = auth_headers(client, username="alice")
    body = _create_config(client, headers)
    config_id = body["id"]

    del_resp = client.delete(
        f"/api/v1/llm-configs/{config_id}", headers=headers
    )
    assert del_resp.status_code == 204

    # The config is gone: listing returns an empty set.
    list_resp = client.get("/api/v1/llm-configs", headers=headers)
    items = (
        list_resp.json()["items"]
        if isinstance(list_resp.json(), dict)
        else list_resp.json()
    )
    assert len(items) == 0


# ---------------------------------------------------------------------------
# POST /llm-configs/{id}/enable
# ---------------------------------------------------------------------------


def test_enable_config(client) -> None:
    """POST /llm-configs/{id}/enable enforces mutual exclusivity."""
    headers = auth_headers(client, username="alice")
    body_a = _create_config(
        client, headers, payload={**CREATE_PAYLOAD, "name": "a"}
    )
    body_b = _create_config(
        client, headers, payload={**CREATE_PAYLOAD, "name": "b"}
    )

    # Enable A first, then B: A must lose its default status.
    client.post(f"/api/v1/llm-configs/{body_a['id']}/enable", headers=headers)
    enable_resp = client.post(
        f"/api/v1/llm-configs/{body_b['id']}/enable", headers=headers
    )
    assert enable_resp.status_code == 200
    enabled = enable_resp.json()
    assert enabled["is_default"] is True
    assert enabled["enabled"] is True

    # Verify A is no longer the default via the list.
    list_resp = client.get("/api/v1/llm-configs", headers=headers)
    items = (
        list_resp.json()["items"]
        if isinstance(list_resp.json(), dict)
        else list_resp.json()
    )
    by_id = {it["id"]: it for it in items}
    assert by_id[body_b["id"]]["is_default"] is True
    assert by_id[body_a["id"]]["is_default"] is False


# ---------------------------------------------------------------------------
# POST /llm-configs/{id}/test
# ---------------------------------------------------------------------------


def test_test_connection(client) -> None:
    """POST /llm-configs/{id}/test returns success when _real_response works."""
    headers = auth_headers(client, username="alice")
    body = _create_config(client, headers)
    config_id = body["id"]

    with patch(
        "app.services.llm_config_service._real_response",
        return_value={"answer": "ok"},
    ):
        resp = client.post(
            f"/api/v1/llm-configs/{config_id}/test", headers=headers
        )

    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["status"] == "success"
    assert result["error"] is None
    assert result["provider"] == "openai"
    assert result["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------


def test_unauthorized_access(client) -> None:
    """User B accessing user A's config returns 404 (not 403)."""
    headers_a = auth_headers(client, username="alice")
    body = _create_config(client, headers_a)
    config_id = body["id"]

    headers_b = auth_headers(client, username="bob")

    # GET /active for user B should return null (no config exists).
    active_resp = client.get("/api/v1/llm-configs/active", headers=headers_b)
    assert active_resp.status_code == 200
    assert active_resp.json()["config"] is None

    # Direct access to A's config must 404.
    for method, path, kwargs in [
        (
            "put",
            f"/api/v1/llm-configs/{config_id}",
            {"json": {"name": "hack"}},
        ),
        ("delete", f"/api/v1/llm-configs/{config_id}", {}),
        ("post", f"/api/v1/llm-configs/{config_id}/enable", {}),
        ("post", f"/api/v1/llm-configs/{config_id}/test", {}),
    ]:
        resp = getattr(client, method)(path, headers=headers_b, **kwargs)
        assert resp.status_code == 404, f"{method.upper()} {path}: {resp.text}"


# ---------------------------------------------------------------------------
# No plaintext leaks anywhere
# ---------------------------------------------------------------------------


def test_response_no_plaintext_api_key(client) -> None:
    """No endpoint response contains the plaintext api_key."""
    headers = auth_headers(client, username="alice")
    body = _create_config(client, headers)
    config_id = body["id"]

    # Exercise every read/enable endpoint and verify no plaintext leak.
    endpoints = [
        ("get", "/api/v1/llm-configs"),
        ("get", f"/api/v1/llm-configs/active"),
        ("post", f"/api/v1/llm-configs/{config_id}/enable"),
    ]
    for method, path in endpoints:
        resp = getattr(client, method)(path, headers=headers)
        assert resp.status_code in (200, 201), resp.text
        assert PLAINTEXT_KEY not in resp.text
