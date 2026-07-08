"""Error logging service.

Central write path for the log center. Call :func:`log_error` whenever a
failure or warning worth diagnosing happens (parse failure, upload failure,
agent error, search error, system error). Success flows never call this.

Security Task B: all ``message`` and ``technical_detail`` text is passed
through :func:`redact_sensitive` before persistence so the log center
never stores Authorization headers, API keys, passwords, or JWTs in
plaintext.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.general_error_log import ErrorLog

# --- Redaction rules (security Task B) --------------------------------------
# Authorization: Bearer <anything> -> Authorization: Bearer ***
_AUTHORIZATION_RE = re.compile(
    r"(Authorization\s*:\s*Bearer\s+)([^\s,;]+)", re.IGNORECASE
)
# field=value patterns for sensitive keys -> field=***
_FIELD_RE = re.compile(
    r"(?<![\w-])(api_key|apiKey|password|passwd|token|secret)\s*[=:]\s*([^\s,;]+)",
    re.IGNORECASE,
)
# sk- prefixed API key fragments -> sk-***
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]+")
# JWT three-segment tokens: eyXXX.eyXXX.SIG (base64url segments).
# Each segment is at least 10 chars to avoid false positives.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")


def redact_sensitive(text: Optional[str]) -> Optional[str]:
    """Mask sensitive substrings in ``text``.

    Applied to every ``message`` / ``technical_detail`` written via
    :func:`log_error` so the log center cannot leak credentials. Returns
    ``None`` unchanged (so nullable columns stay nullable).
    """
    if not text:
        return text
    out = text
    out = _JWT_RE.sub("<jwt:***>", out)
    out = _AUTHORIZATION_RE.sub(r"\1***", out)
    out = _SK_RE.sub("sk-***", out)
    out = _FIELD_RE.sub(
        lambda m: f"{m.group(1)}=***", out, count=0
    )
    return out


def log_error(
    db: Session,
    user_id: int,
    *,
    category: str,
    title: str,
    message: str,
    level: str = "error",
    status: str = "open",
    technical_detail: Optional[str] = None,
    course_id: Optional[int] = None,
    material_id: Optional[int] = None,
    agent_run_id: Optional[int] = None,
    request_path: Optional[str] = None,
    retry_count: int = 0,
    max_retries: Optional[int] = None,
    commit: bool = True,
) -> ErrorLog:
    """Persist a single failure/warning record.

    Parameters mirror the ``ErrorLog`` columns. ``commit=False`` lets a
    caller batch the insert into its own transaction (e.g. when the log
    is written alongside a status update in the same commit).

    Security Task B: ``message`` and ``technical_detail`` are redacted
    before persistence.
    """
    log = ErrorLog(
        user_id=user_id,
        category=category,
        level=level,
        status=status,
        title=title,
        message=redact_sensitive(message),
        technical_detail=redact_sensitive(technical_detail),
        course_id=course_id,
        material_id=material_id,
        agent_run_id=agent_run_id,
        request_path=request_path,
        retry_count=retry_count,
        max_retries=max_retries,
    )
    db.add(log)
    if commit:
        db.commit()
        db.refresh(log)
    else:
        db.flush()
    return log
