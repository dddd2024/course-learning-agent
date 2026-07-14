from __future__ import annotations

import pytest
from unittest.mock import patch
from pathlib import Path

from app.agents.llm import call_llm_with_meta
from app.services.real_llm_acceptance_service import (
    RealLLMAcceptanceError,
    assert_real_llm_meta,
    base_url_host,
    redact_secrets,
    scan_artifact_tree,
    safe_failure_record,
)


def test_real_meta_with_identity_and_no_degradation_passes() -> None:
    assert_real_llm_meta({
        "meta_observed": True,
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
    meta.setdefault("meta_observed", True)
    with pytest.raises(RealLLMAcceptanceError, match=code):
        assert_real_llm_meta(meta)


@pytest.mark.parametrize("meta", [
    {"actual_provider": "user", "actual_model": "m", "fallback_used": False, "degraded": False},
    {"meta_observed": False, "actual_provider": "user", "actual_model": "m", "fallback_used": False, "degraded": False},
    {"meta_observed": True, "requested_provider": "user", "actual_model": "m", "fallback_used": False, "degraded": False},
    {"meta_observed": True, "actual_provider": "user", "actual_model": "m", "fallback_used": None, "degraded": False},
])
def test_real_meta_requires_observed_actual_values(meta: dict) -> None:
    with pytest.raises(RealLLMAcceptanceError):
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


def test_artifact_secret_scan_detects_encoded_and_header_forms(tmp_path: Path) -> None:
    key = "sk-secret value-12345"
    (tmp_path / "full.txt").write_text(key, encoding="utf-8")
    assert scan_artifact_tree(tmp_path, key)["status"] == "failed"
    (tmp_path / "full.txt").write_text("key=sk-secret%20value-12345", encoding="utf-8")
    assert scan_artifact_tree(tmp_path, key)["status"] == "failed"
    (tmp_path / "full.txt").write_text("Authorization: Bearer opaque-value", encoding="utf-8")
    assert scan_artifact_tree(tmp_path, key)["status"] == "failed"


def test_artifact_secret_scan_allows_plain_token_word(tmp_path: Path) -> None:
    (tmp_path / "safe.txt").write_text("The token bucket algorithm is explained here.", encoding="utf-8")
    result = scan_artifact_tree(tmp_path, "sk-secret-value-12345")
    assert result["status"] == "passed"
    assert result["files_scanned"] == 1
    assert result["patterns_checked"] >= 10


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
