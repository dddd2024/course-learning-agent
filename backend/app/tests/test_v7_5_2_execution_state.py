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
    "real_llm_acceptance_two_runs",
    "windows_launcher_smoke",
    "remote_ci_verification",
}


def _load_state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def test_v7_5_2_records_honest_current_state() -> None:
    state = _load_state()

    assert state["version"] == "v7.5.2"
    assert state["base_commit"] == "9552c2ecd5f0b70c9be6a61eb02958ea4becfe2a"
    assert state["branch"] == "codex/v7-5-2-r4-real-llm-rc3-closure"
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


def test_remote_ci_unavailable_is_not_success_or_release_ready() -> None:
    state = _load_state()
    if state["remote_ci"] == "unavailable":
        assert state["overall_status"] == "in_progress"
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
    assert all(task["status"] in {"done", "superseded"} for task in state["tasks"].values())
    assert state["remote_ci"] == "success"
    artifact = PROJECT_DIR / "artifacts" / "verification" / "v7-audit-recovery" / "summary.json"
    assert artifact.exists(), "verified state requires final audit evidence"
    summary = json.loads(artifact.read_text(encoding="utf-8"))
    assert summary["commit_sha"] == gate["commit_sha"]
    assert summary["playwright_failed"] == summary["playwright_skipped"] == 0
    assert summary["remote_ci"] == "success"
    assert summary["legacy_migration"] == "passed"


def test_done_tasks_have_test_evidence() -> None:
    state = _load_state()
    for task_id, task in state["tasks"].items():
        if task["status"] == "done":
            assert task["tests_run"], (
                f"Task {task_id} is done but has empty tests_run; "
                "release evidence cannot be bypassed"
            )


def test_v7_5_2_scope_matches_r4_real_llm_release_state() -> None:
    scope = SCOPE_PATH.read_text(encoding="utf-8")
    lower_scope = scope.lower()

    assert "R4 scope" in scope
    assert "9552c2ecd5f0b70c9be6a61eb02958ea4becfe2a" in scope
    assert "real_llm_acceptance_harness" in scope
    assert "real_llm_no_mock_fallback_proof" in scope
    assert "windows_launcher_smoke" in scope
    assert "rc3_evidence_transaction" in scope
    assert "in_progress" in scope
    assert "v1.0.0-rc3" in scope
    assert "cross-windows/linux" in lower_scope
    assert "bbox" in lower_scope
