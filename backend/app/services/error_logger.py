"""Error logging service.

Central write path for the log center. Call :func:`log_error` whenever a
failure or warning worth diagnosing happens (parse failure, upload failure,
agent error, search error, system error). Success flows never call this.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.general_error_log import ErrorLog


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
    """
    log = ErrorLog(
        user_id=user_id,
        category=category,
        level=level,
        status=status,
        title=title,
        message=message,
        technical_detail=technical_detail,
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
