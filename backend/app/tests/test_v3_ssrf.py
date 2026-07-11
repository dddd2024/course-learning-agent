"""V3 SSRF Protection tests (BASE-V3-02).

These tests capture audit blockers in SSRF protection where:

- ``validate_llm_base_url`` skips all private-address checks when
  ``ENVIRONMENT != "production"``, allowing localhost, loopback, and
  RFC-1918 addresses in development mode.
- The cloud metadata endpoint ``169.254.169.254`` is not rejected in
  development mode.
- There is no request-time SSRF validation — checks happen only at
  config-save time (and only in production).
- DNS rebinding is possible: a URL that resolves to a public IP at save
  time can later resolve to a private IP, and the system will not
  detect the change.

Written to FAIL on the current codebase.
"""
import socket
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services.llm_config_security import validate_llm_base_url
from app.tests.conftest import auth_headers

PRIVATE_URLS = [
    "http://localhost:11434/v1",
    "http://127.0.0.1:11434/v1",
    "http://[::1]:11434/v1",
    "http://10.0.0.1:11434/v1",
    "http://172.16.0.1:11434/v1",
    "http://172.31.255.255:11434/v1",
    "http://192.168.1.1:11434/v1",
    "http://192.168.0.100:8080/v1",
]

METADATA_URL = "http://169.254.169.254/latest/meta-data/"


@pytest.fixture(autouse=True)
def _ensure_dev_environment(monkeypatch):
    """Force ENVIRONMENT to 'development' and SSRF protection on.

    The conftest autouse fixture sets ``ALLOW_PRIVATE_LLM_ENDPOINTS=True``
    for all tests so existing tests pass.  This V3 SSRF test suite must
    override that to ``False`` so it can verify that private addresses
    are rejected by default.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_LLM_ENDPOINTS", False)


@pytest.mark.parametrize("url", PRIVATE_URLS)
def test_private_addresses_rejected_by_default(url: str) -> None:
    """Private / loopback / link-local addresses must be rejected by default.

    The current code only checks private addresses when
    ``ENVIRONMENT == "production"``.  The V3 fix should reject them in
    all environments so a misconfigured dev instance cannot be used to
    probe internal services.
    """
    with pytest.raises(ValueError, match="私有|保留|本地|private|reserved|local"):
        validate_llm_base_url(url)


def test_cloud_metadata_address_rejected() -> None:
    """169.254.169.254 (cloud metadata) must be rejected by default.

    The AWS/GCP/Azure instance metadata endpoint is a common SSRF
    target.  The current code only blocks it in production mode.
    """
    with pytest.raises(ValueError, match="元数据|metadata|169\\.254|私有|保留|private|reserved"):
        validate_llm_base_url(METADATA_URL)


def test_request_time_ssrf_validation_in_dev_mode(
    client, monkeypatch
) -> None:
    """Even in dev mode, request-time SSRF validation should apply.

    The V3 plan requires that SSRF validation is not limited to
    config-save time.  When an actual LLM request is made (e.g. via
    the test-connection endpoint), the target URL should be re-validated
    so a URL that was valid at save time but now resolves to a private
    IP is rejected.

    This test saves a config whose URL initially resolves to a public
    IP, then makes a test-connection request after DNS has been
    re-pointed to a private address.  The request should be rejected.
    """
    headers = auth_headers(client, username="ssrf_user")

    # Step 1: save a config with a public-looking URL.  Mock DNS so the
    # save-time validation (after V3 fix) sees a public IP.
    def public_dns(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("104.18.6.192", 443))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)

    save_resp = client.post(
        "/api/v1/llm-configs",
        json={
            "provider": "openai",
            "name": "test-openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-dummy-key",
            "model": "gpt-4o-mini",
        },
        headers=headers,
    )
    assert save_resp.status_code in (200, 201), save_resp.text
    config_id = save_resp.json()["id"]

    # Step 2: simulate DNS rebinding — the hostname now resolves to a
    # private IP.
    def private_dns(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.99", 443))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", private_dns)

    # Step 3: make a test-connection request.  The V3 fix should
    # re-validate the URL at request time and reject it because the
    # hostname now resolves to a private IP.
    test_resp = client.post(
        f"/api/v1/llm-configs/{config_id}/test",
        headers=headers,
    )
    # The request should be rejected (400/403), not succeed (200) or
    # fail with a connection error (502/503).
    assert test_resp.status_code in (400, 403), (
        f"Expected 400/403 for request-time SSRF rejection, got "
        f"{test_resp.status_code}: {test_resp.text}"
    )


def test_config_save_rejects_dns_rebinding_to_private(
    client, monkeypatch
) -> None:
    """Config save with valid URL but DNS change to private IP should be rejected.

    Even at config-save time, if the URL's hostname resolves to a
    private IP, the save should be rejected — regardless of the
    ENVIRONMENT setting.
    """
    headers = auth_headers(client, username="ssrf_user2")

    # Mock DNS so that any hostname resolves to 10.0.0.99.
    def fake_getaddrinfo(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.99", 443))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    # The URL looks public but DNS resolves to a private IP.
    save_resp = client.post(
        "/api/v1/llm-configs",
        json={
            "provider": "openai",
            "name": "test-openai-rebind",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-dummy-key",
            "model": "gpt-4o-mini",
        },
        headers=headers,
    )
    assert save_resp.status_code in (400, 403), (
        f"Expected 400/403 when DNS resolves to private IP, got "
        f"{save_resp.status_code}: {save_resp.text}"
    )


def test_public_url_accepted_in_dev_mode() -> None:
    """A genuinely public URL should be accepted in dev mode.

    This is a companion test to ensure the V3 fix does not over-block
    legitimate public endpoints.
    """
    # Mock DNS to return a public IP for api.openai.com.
    def fake_getaddrinfo(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("104.18.6.192", 443))
        ]

    with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo):
        result = validate_llm_base_url("https://api.openai.com/v1")
    assert result == "https://api.openai.com/v1"
