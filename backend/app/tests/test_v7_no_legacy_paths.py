"""Guardrails that prevent V7 production paths falling back to legacy flows."""
from __future__ import annotations

import inspect

from app.api.v1.endpoints import plans
from app.services import task_execution_service


def test_plan_execution_endpoints_delegate_to_execution_service() -> None:
    source = inspect.getsource(plans)

    assert "start_task_service(" in source
    assert "record_task_event_service(" in source
    assert "verify_task_service(" in source
    assert "override_task_service(" in source


def test_execution_service_uses_the_unified_transition_engine() -> None:
    source = inspect.getsource(task_execution_service)

    assert "transition_task(db, task, \"start\"" in source
    assert "transition_task(db, task, \"record_event\"" in source
    assert '"verify", user_id' in source
