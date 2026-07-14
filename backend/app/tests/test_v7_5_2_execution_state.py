"""State-contract tests for the V7.5.2 RC blocker recovery round."""
from __future__ import annotations

import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
SCOPE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-2-scope.md"

REQUIRED_RELEASE_GATES = {
    "backend_full_pytest",
    "frontend_unit_tests",
    "frontend_type_check",
    "frontend_build",
    "migration_dry_run_and_smoke",
    "playwright_e2e",
    "v7_acceptance_verification",
}


def _load_state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def test_v7_5_2_records_honest_current_state() -> None:
    state = _load_state()

    assert state["version"] == "v7.5.2"
    assert state["base_commit"] == "fd5198b63e25b869b3a31fb0e7178b9c02f3c294"
    assert state["overall_status"] in {"in_progress", "verified_locally"}

    if state["overall_status"] == "in_progress":
        assert state["local_closure"] is None
        assert state["release_candidate"] is None
        assert state["audit_blockers"], "in-progress state must name active blockers"
        assert state["current_task"] in state["tasks"]
        assert state["tasks"][state["current_task"]]["status"] == "in_progress"
    else:
        assert state["local_closure"] == "V7.5.2_RC_BLOCKERS_CLOSED_LOCALLY"
        assert state["release_candidate"] == "v1.0.0-rc3"
        assert state["audit_blockers"] == []
        assert state["current_task"] is None


def test_failed_or_incomplete_gate_forces_in_progress() -> None:
    state = _load_state()
    gate = state.get("latest_gate") or {}
    failed_gates = gate.get("failed_gates") or []
    not_run_gates = gate.get("not_run_gates") or []

    has_failed_count = any(int(item.get("failed", 0)) > 0 for item in failed_gates)
    if gate.get("overall") != "success" or has_failed_count or not_run_gates:
        assert state["overall_status"] == "in_progress"
        assert state["local_closure"] is None
        assert state["release_candidate"] is None


def test_verified_locally_requires_every_release_gate() -> None:
    state = _load_state()
    if state["overall_status"] != "verified_locally":
        return

    gate = state.get("latest_gate") or {}
    assert gate.get("overall") == "success"
    assert gate.get("failed_gates") == []
    assert gate.get("not_run_gates") == []
    assert REQUIRED_RELEASE_GATES.issubset(set(gate.get("passed_gates") or []))
    assert all(task["status"] == "done" for task in state["tasks"].values())


def test_done_tasks_have_test_evidence() -> None:
    state = _load_state()
    for task_id, task in state["tasks"].items():
        if task["status"] == "done":
            assert task["tests_run"], (
                f"Task {task_id} is done but has empty tests_run; "
                "release evidence cannot be bypassed"
            )


def test_v7_5_2_scope_matches_reopened_release_state() -> None:
    scope = SCOPE_PATH.read_text(encoding="utf-8")
    lower_scope = scope.lower()

    assert "new_version_image_binding" in scope
    assert "page_asset_expected_page_coverage" in scope
    assert "page_asset_db_fs_compensation" in scope
    assert "e2e_environment_isolation" in scope
    assert "e2e_user_path_acceptance" in scope
    assert "v7_acceptance_verification" in scope
    assert "47 passed, 27 failed, 2 did not run" in scope
    assert "in_progress" in scope
    assert "v1.0.0-rc3" in scope
    assert "cross-windows/linux" in lower_scope
    assert "bbox" in lower_scope
