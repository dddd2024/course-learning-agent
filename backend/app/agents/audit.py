"""AgentAudit — lightweight audit-trail helper for agent executions.

This module is the single entry point for recording agent runs:

- ``create_run`` opens a new ``AgentRun`` row with ``status='running'``
  and ``started_at=now``.
- ``add_step`` appends an ``AgentStep`` row to an existing run, capturing
  the step's name / index / input / output / duration / status so the
  full trace can be replayed later.
- ``finish_run`` closes the run with ``status`` / ``finished_at`` /
  ``duration_ms`` / ``output_summary`` / ``error_message``.

Callers should wrap audit calls in ``try/except`` so an audit failure
never breaks the main flow — the audit is observability, not part of the
critical path.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AgentRun, AgentStep


def _to_json(value: Any) -> str | None:
    """Serialise ``value`` to a JSON string (``None`` stays ``None``)."""
    if value is None:
        return None
    if isinstance(value, str):
        # Already a string — store as-is. This keeps the helper tolerant
        # of callers that pre-serialise their payloads.
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


class AgentAudit:
    """Agent execution audit tool.

    All methods are static and operate on the caller's SQLAlchemy
    session. They never commit the top-level transaction — the caller is
    responsible for committing / rolling back the run as a whole — but
    they do ``flush`` so the new row gets an id that the caller can use
    immediately (e.g. ``add_step`` needs the ``run_id``).
    """

    @staticmethod
    def create_run(
        db: Session,
        user_id: int,
        run_type: str,
        input_summary: Any = None,
        prompt_version: str | None = None,
        model_name: str = "mock",
        provider: str | None = None,
        config_id: int | None = None,
    ) -> AgentRun:
        """Create a run record with ``status='running'`` and ``started_at=now``.

        ``provider`` / ``config_id`` trace which LLM backed the call:
        ``provider='mock'`` for mock mode, ``'real'`` for a system-configured
        LLM, ``'user'`` for a user-supplied config (in which case
        ``config_id`` points at the ``UserLLMConfig`` row). Both default to
        ``None`` so existing callers keep working untouched. The api_key is
        never recorded — only the config id reference is.
        """
        run = AgentRun(
            user_id=user_id,
            run_type=run_type,
            status="running",
            input_summary=_to_json(input_summary),
            prompt_version=prompt_version,
            model_name=model_name,
            provider=provider,
            requested_provider=provider,
            requested_model=model_name,
            config_id=config_id,
            started_at=datetime.now(),
        )
        db.add(run)
        db.flush()
        return run

    @staticmethod
    def add_step(
        db: Session,
        run_id: int,
        step_name: str,
        step_index: int,
        input_data: Any = None,
        output_data: Any = None,
        duration_ms: int | None = None,
        status: str = "success",
        error_message: str | None = None,
    ) -> AgentStep:
        """Add a step record to an existing run."""
        step = AgentStep(
            run_id=run_id,
            step_name=step_name,
            step_index=step_index,
            input_data=_to_json(input_data),
            output_data=_to_json(output_data),
            duration_ms=duration_ms,
            status=status,
            error_message=error_message,
        )
        db.add(step)
        db.flush()
        return step

    @staticmethod
    def finish_run(
        db: Session,
        run_id: int,
        status: str = "success",
        output_summary: Any = None,
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> AgentRun | None:
        """Mark a run as finished: set status / finished_at / duration_ms."""
        run = (
            db.query(AgentRun)
            .filter(AgentRun.id == run_id)
            .first()
        )
        if run is None:
            return None
        run.status = status
        run.finished_at = datetime.now()
        if duration_ms is not None:
            run.duration_ms = duration_ms
        if output_summary is not None:
            run.output_summary = _to_json(output_summary)
        if error_message is not None:
            run.error_message = error_message
        db.flush()
        return run

    @staticmethod
    def update_run_meta(
        db: Session,
        run_id: int | None,
        model_name: str | None = None,
        provider: str | None = None,
        meta: dict | None = None,
    ) -> None:
        """Update an existing AgentRun's model_name/provider after the LLM
        call completes, so the audit record reflects the actual provider
        used (which may differ from the pre-call guess due to fallback).
        """
        if run_id is None:
            return
        try:
            run = db.query(AgentRun).filter_by(id=run_id).first()
            if run is not None:
                if model_name is not None:
                    run.model_name = model_name
                if provider is not None:
                    run.provider = provider
                if meta:
                    run.actual_provider = meta.get("actual_provider", provider)
                    run.actual_model = meta.get("actual_model", model_name)
                    run.fallback_used = 1 if meta.get("fallback_used") else 0
                    run.fallback_reason = meta.get("fallback_reason")
                    if meta.get("degraded"):
                        run.status = "degraded"
                db.flush()
        except Exception:
            pass  # audit must not break the main flow


__all__ = ["AgentAudit"]
