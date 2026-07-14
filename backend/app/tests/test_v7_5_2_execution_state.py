"""State-contract tests for the V7.5.2 RC blocker fix round."""
from __future__ import annotations

import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
SCOPE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-2-scope.md"
REQUIRED_GATES = {
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


def test_v7_5_2_records_honest_in_progress_state() -> None:
    state = _load_state()

    assert state["version"] == "v7.5.2"
    assert state["base_commit"] == "fd5198b63e25b869b3a31fb0e7178b9c02f3c294"
    assert set(state["required_gates"]) == REQUIRED_GATES

    assert state["overall_status"] == "in_progress"
    assert state["local_closure"] is None
    assert state["closure_evidence"] is None
    assert state["release_candidate"] is None
    assert state["current_task"] in state["tasks"]
    assert state["tasks"][state["current_task"]]["status"] == "in_progress"
    assert state["audit_blockers"]

    regression = state["latest_regression"]
    assert regression["gates"]["playwright_e2e"] == "failed"
    assert regression["gates"]["v7_acceptance_verification"] == "not_run"
    assert regression["playwright_summary"] == {
        "passed": 47,
        "failed": 27,
        "not_run": 2,
    }


def test_verified_locally_requires_one_complete_green_regression() -> None:
    """A release closure is invalid unless every required gate passed together."""
    state = _load_state()
    if state["overall_status"] != "verified_locally":
        return

    assert state["local_closure"] == "V7.5.2_RC_BLOCKERS_CLOSED_LOCALLY"
    assert state["release_candidate"] == "v1.0.0-rc3"
    assert state["audit_blockers"] == []
    assert state["current_task"] is None
    assert state["closure_evidence"] is not None

    gates = state["latest_regression"]["gates"]
    assert set(gates) == REQUIRED_GATES
    assert all(gates[name] == "passed" for name in REQUIRED_GATES)

    summary = state["latest_regression"]["playwright_summary"]
    assert summary["failed"] == 0
    assert summary["not_run"] == 0

    for task_id, task in state["tasks"].items():
        assert task["status"] == "done", f"Task {task_id} is not done"
        assert task["tests_run"], f"Task {task_id} has no test evidence"
        assert task["remaining"] == [], f"Task {task_id} still has remaining work"


def test_failed_or_skipped_gate_forbids_release_metadata() -> None:
    state = _load_state()
    gates = state["latest_regression"]["gates"]
    has_non_passing_gate = any(status != "passed" for status in gates.values())

    if has_non_passing_gate:
        assert state["overall_status"] != "verified_locally"
        assert state["local_closure"] is None
        assert state["closure_evidence"] is None
        assert state["release_candidate"] is None


def test_v7_5_2_scope_lists_p0_and_p1_issues() -> None:
    scope = SCOPE_PATH.read_text(encoding="utf-8")
    assert "new_version_image_binding" in scope
    assert "page_asset_expected_page_coverage" in scope
    assert "page_asset_db_fs_compensation" in scope
    assert "e2e_environment_isolation" in scope
    assert "weak assertions" in scope.lower() or "E2E" in scope
    assert "corrupted" in scope.lower() or "NULL" in scope
    assert "remote ci" in scope.lower()
    assert "bbox" in scope.lower()
    assert "v1.0.0-rc3" in scope
