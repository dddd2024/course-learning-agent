"""AgentAudit — lightweight audit-trail helper for agent executions.

This module is the single entry point for recording agent runs:

- ``create_run`` opens a new ``AgentRun`` row with ``status='running'``
  and ``started_at=now``.
- ``add_step`` appends an ``AgentStep`` row to an existing run, capturing
  the step's name / index / input / output / duration / status so the
  full trace can be replayed later.
- ``update_run_meta`` writes requested/actual provider, model, and
  fallback_chain to the run — it does NOT touch ``status``.
- ``finalize_run`` closes the run, computing the final status from
  error / fallback_used / evidence_status. It never downgrades a
  previously set degraded/failed/insufficient_evidence status to
  ``success``.
- ``finish_run`` is kept for backward compatibility; when called with
  ``status='success'`` it preserves an already-set non-success status.

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

# Status constants — centralised so all agents use the same vocabulary.
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_DEGRADED = "degraded"
STATUS_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# Statuses that must NOT be silently overridden by a later ``success``.
_TERMINAL_STATUSES = frozenset({
    STATUS_DEGRADED,
    STATUS_FAILED,
    STATUS_INSUFFICIENT_EVIDENCE,
})


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
        """Mark a run as finished: set status / finished_at / duration_ms.

        When ``status='success'`` is requested but the run is already in
        a terminal non-success status (degraded / failed /
        insufficient_evidence), the existing status is preserved so a
        late ``finish_run(success)`` call never masks a prior failure.
        """
        run = (
            db.query(AgentRun)
            .filter(AgentRun.id == run_id)
            .first()
        )
        if run is None:
            return None
        # Preserve terminal statuses: a ``success`` finish must not
        # override a previously set degraded/failed/insufficient_evidence.
        if status == STATUS_SUCCESS and run.status in _TERMINAL_STATUSES:
            pass  # keep existing status
        else:
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
    def finalize_run(
        db: Session,
        run_id: int,
        error: str | None = None,
        fallback_used: bool = False,
        evidence_status: str | None = None,
        output_summary: Any = None,
        duration_ms: int | None = None,
    ) -> AgentRun | None:
        """Close a run, computing the final status from its outcome.

        Status priority (highest first):
        1. ``error`` is not None → ``failed``
        2. ``fallback_used`` is True → ``degraded``
        3. ``evidence_status`` indicates insufficient evidence →
           ``insufficient_evidence``
        4. No issues → ``success``

        CRITICAL: if the run is already in a terminal non-success status
        (degraded / failed / insufficient_evidence) and the computed
        status would be ``success``, the existing status is preserved.
        A terminal status is never silently downgraded to ``success``.
        """
        run = (
            db.query(AgentRun)
            .filter(AgentRun.id == run_id)
            .first()
        )
        if run is None:
            return None

        # Compute the new status based on the outcome.
        if error is not None:
            new_status = STATUS_FAILED
        elif evidence_status in ("insufficient", "not_required"):
            new_status = STATUS_INSUFFICIENT_EVIDENCE
        elif fallback_used or run.provider == "mock":
            new_status = STATUS_DEGRADED
        else:
            new_status = STATUS_SUCCESS

        rank = {STATUS_SUCCESS: 0, STATUS_DEGRADED: 1, STATUS_INSUFFICIENT_EVIDENCE: 2, STATUS_CANCELLED: 3, STATUS_FAILED: 4}
        if rank.get(run.status, 0) > rank.get(new_status, 0):
            new_status = run.status

        run.status = new_status
        run.finished_at = datetime.now()
        if duration_ms is not None:
            run.duration_ms = duration_ms
        if output_summary is not None:
            run.output_summary = _to_json(output_summary)
        if error is not None:
            run.error_message = error
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
        """Update an existing AgentRun's provider/model/fallback metadata.

        Writes requested/actual provider, model, fallback_used,
        fallback_reason, and fallback_chain. It does NOT modify
        ``status`` — status is set by ``finalize_run`` based on the
        overall outcome.
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
                    chain = meta.get("fallback_chain")
                    if chain is not None:
                        run.fallback_chain = _to_json(chain)
                db.flush()
        except Exception:
            pass  # audit must not break the main flow


__all__ = [
    "AgentAudit",
    "STATUS_RUNNING",
    "STATUS_SUCCESS",
    "STATUS_DEGRADED",
    "STATUS_INSUFFICIENT_EVIDENCE",
    "STATUS_FAILED",
    "STATUS_CANCELLED",
]
