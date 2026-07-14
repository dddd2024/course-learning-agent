"""Strict, secret-safe checks used by the isolated real-LLM acceptance run.

Production callers intentionally retain their graceful fallback to mock.  A
release acceptance run must instead reject every degraded path, even if its
answer happens to look valid.  This module contains no network or persistence
code so it can be reused by the CLI harness and tested independently.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit


class RealLLMAcceptanceError(RuntimeError):
    """Raised when a result cannot be accepted as a genuine provider call."""


_SECRET_PATTERNS = (
    # Authorization values and common API-key assignments.
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret)\s*[:=]\s*)([^\s,;]+)"), r"\1[REDACTED]"),
    # OpenAI-style keys can appear inside third-party HTTP errors.
    (re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b"), "[REDACTED]"),
)


def redact_secrets(value: Any) -> str:
    """Return a bounded, display-safe error string without credentials."""
    text = str(value or "")
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:500]


def base_url_host(value: str) -> str:
    """Return only scheme and host (plus non-default port) for artifacts."""
    parsed = urlsplit(value or "")
    if not parsed.scheme or not parsed.hostname:
        return ""
    default_port = {"https": 443, "http": 80}.get(parsed.scheme)
    port = f":{parsed.port}" if parsed.port and parsed.port != default_port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def assert_real_llm_meta(meta: dict[str, Any]) -> None:
    """Reject mock, fallback, degraded, and anonymous model outcomes."""
    if meta.get("meta_observed") is not True:
        raise RealLLMAcceptanceError("REAL_LLM_META_MISSING")
    if meta.get("actual_provider") == "mock" or meta.get("provider") == "mock":
        raise RealLLMAcceptanceError("REAL_LLM_FELL_BACK_TO_MOCK")
    if not str(meta.get("actual_provider") or "").strip() or meta.get("actual_provider") == "unknown":
        raise RealLLMAcceptanceError("REAL_LLM_META_MISSING")
    if meta.get("fallback_used"):
        raise RealLLMAcceptanceError("REAL_LLM_FALLBACK_USED")
    if meta.get("degraded"):
        raise RealLLMAcceptanceError("REAL_LLM_DEGRADED")
    if meta.get("fallback_used") is not False:
        raise RealLLMAcceptanceError("REAL_LLM_FALLBACK_STATE_MISSING")
    if not str(meta.get("actual_model") or meta.get("model_name") or "").strip():
        raise RealLLMAcceptanceError("REAL_LLM_MODEL_IDENTITY_MISSING")


def scan_artifact_tree(root: Any, raw_secret: str) -> dict[str, int | str]:
    """Scan generated acceptance artifacts without returning matched secrets.

    The result deliberately exposes only counts: callers may record it in a
    release artifact without turning the scanner itself into a disclosure path.
    """
    from pathlib import Path

    root_path = Path(root)
    secret_forms = [raw_secret, quote(raw_secret, safe=""), quote_plus(raw_secret), json.dumps(raw_secret)[1:-1]]
    patterns = [
        re.compile(re.escape(value)) for value in secret_forms if value
    ] + [
        re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+\S+"),
        re.compile(r"(?i)api_key\s*[:=]\s*\S+"),
        re.compile(r"(?i)api-key\s*[:=]\s*\S+"),
        re.compile(r"(?i)token\s*[:=]\s*\S+"),
        re.compile(r"(?i)secret\s*[:=]\s*\S+"),
        re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b"),
        re.compile(r"\bREAL_LLM_API_KEY\b"),
    ]
    files_scanned = 0
    matches = 0
    if root_path.exists():
        for path in root_path.rglob("*"):
            if not path.is_file():
                continue
            files_scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            matches += sum(1 for pattern in patterns if pattern.search(text))
    return {
        "status": "passed" if matches == 0 else "failed",
        "files_scanned": files_scanned,
        "patterns_checked": len(patterns),
        "matches": matches,
    }


def safe_failure_record(error: BaseException | str) -> dict[str, str]:
    """Create the only error representation permitted in a run artifact."""
    if isinstance(error, RealLLMAcceptanceError):
        code = str(error)
    else:
        code = "REAL_LLM_REQUEST_FAILED"
    return {"error_code": code, "error": redact_secrets(error)}


__all__ = [
    "RealLLMAcceptanceError",
    "assert_real_llm_meta",
    "base_url_host",
    "redact_secrets",
    "scan_artifact_tree",
    "safe_failure_record",
]
