from __future__ import annotations

import pytest
from unittest.mock import patch

from app.agents.llm import call_llm_with_meta
from app.services.real_llm_acceptance_service import (
    RealLLMAcceptanceError,
    assert_real_llm_meta,
    base_url_host,
    redact_secrets,
    safe_failure_record,
)


def test_real_meta_with_identity_and_no_degradation_passes() -> None:
    assert_real_llm_meta({
        "actual_provider": "user",
        "actual_model": "gpt-test",
        "fallback_used": False,
        "degraded": False,
    })


@pytest.mark.parametrize(
    ("meta", "code"),
    [
        ({"actual_provider": "mock", "actual_model": "mock"}, "REAL_LLM_FELL_BACK_TO_MOCK"),
        ({"actual_provider": "user", "actual_model": "m", "fallback_used": True}, "REAL_LLM_FALLBACK_USED"),
        ({"actual_provider": "user", "actual_model": "m", "degraded": True}, "REAL_LLM_DEGRADED"),
        ({"actual_provider": "user", "fallback_used": False, "degraded": False}, "REAL_LLM_MODEL_IDENTITY_MISSING"),
    ],
)
def test_real_meta_rejects_non_strict_outcomes(meta: dict, code: str) -> None:
    with pytest.raises(RealLLMAcceptanceError, match=code):
        assert_real_llm_meta(meta)


def test_redaction_removes_key_and_authorization() -> None:
    error = "HTTP 401 Authorization: Bearer sk-supersecret123 api_key=another-secret"
    redacted = redact_secrets(error)
    assert "supersecret" not in redacted
    assert "another-secret" not in redacted
    assert "[REDACTED]" in redacted
    record = safe_failure_record(error)
    assert record["error_code"] == "REAL_LLM_REQUEST_FAILED"
    assert "supersecret" not in record["error"]


def test_base_url_host_drops_path_query_and_credentials() -> None:
    assert base_url_host("https://person:secret@api.example.com:8443/v1?token=x") == "https://api.example.com:8443"


@pytest.mark.parametrize("error", [
    RuntimeError("request timed out with Authorization: Bearer sk-timeout-secret"),
    RuntimeError("LLM service returned non-JSON api_key=sk-non-json-secret"),
    RuntimeError("business schema did not include questions"),
])
def test_real_acceptance_rejects_provider_failures_even_if_runtime_falls_back(error: RuntimeError) -> None:
    """Timeout/non-JSON/schema failures can degrade production, never RC acceptance."""
    with patch("app.agents.llm._real_response", side_effect=error):
        _result, meta = call_llm_with_meta(
            "prompt", "course_qa", user_config={"model": "real-model"}
        )
    with pytest.raises(RealLLMAcceptanceError):
        assert_real_llm_meta(meta)
    assert "sk-timeout-secret" not in redact_secrets(meta.get("fallback_reason"))
    assert "sk-non-json-secret" not in redact_secrets(meta.get("fallback_reason"))
