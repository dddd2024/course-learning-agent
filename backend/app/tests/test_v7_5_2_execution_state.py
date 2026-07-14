"""State-contract tests for the V7.5.2 RC blocker recovery rounds."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
SCOPE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-2-scope.md"
EVIDENCE_VERIFIER = PROJECT_DIR / "scripts" / "verify_real_llm_evidence.py"

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
    assert state["base_commit"] in {
        "a07b9332ac0a11ef53bd4e9081b845c1073da445",
        "4cd1d2d2bfe6db49f370f7cfa9a7cba15bb1ba84",
    }
    assert state["branch"].startswith("codex/v7-5-2-")
    assert state["overall_status"] in {"in_progress", "verified_locally"}

    is_r6 = "AUDIT-R6-01" in state["tasks"]
    if state["overall_status"] == "in_progress":
        assert state["local_closure"] is None
        assert state["release_candidate"] is None
        assert state["audit_blockers"], "in-progress state must name active blockers"
        assert state["current_task"] in state["tasks"]
        assert state["tasks"][state["current_task"]]["status"] == "in_progress"
    else:
        if is_r6:
            assert state["local_closure"] == "V7.5.2_R6_VERIFIED_LOCALLY"
            assert state["release_candidate"] is None
            expected_blockers = [] if state["remote_ci"] == "success" else ["remote_ci_verification"]
            assert state["audit_blockers"] == expected_blockers
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

    has_failed_count = any(
        isinstance(item, dict) and int(item.get("failed", 0)) > 0
        for item in failed_gates
    )
    local_pending_only = set(not_run_gates) <= {"remote_ci_verification"}
    if (
        gate.get("overall") != "success"
        or has_failed_count
        or (not_run_gates and not local_pending_only)
    ):
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
    assert set(gate.get("not_run_gates") or []) <= {"remote_ci_verification"}
    required_local = REQUIRED_RELEASE_GATES - {
        "windows_launcher_smoke",
        "remote_ci_verification",
    }
    assert required_local.issubset(set(gate.get("passed_gates") or []))
    assert all(
        task["status"] in {"done", "superseded"}
        for task in state["tasks"].values()
    )
    if "AUDIT-R6-01" in state["tasks"]:
        assert state["release_candidate"] is None
    assert state["remote_ci"] in {"pending", "success"}
    assert state["closure_evidence"]["tested_code_sha"] == gate["commit_sha"]
    assert len(state["closure_evidence"]["real_llm_runs"]) == 2


def test_r6_verified_state_references_two_recomputable_compact_bundles() -> None:
    state = _load_state()
    if "AUDIT-R6-01" not in state["tasks"] or state["overall_status"] != "verified_locally":
        return

    evidence = state["closure_evidence"]
    assert evidence["real_llm_runs"] == ["r6-c1-a", "r6-c1-b"]
    assert len(evidence["evidence_paths"]) == len(evidence["real_llm_runs"])
    for relative_path, run_id in zip(evidence["evidence_paths"], evidence["real_llm_runs"]):
        root = PROJECT_DIR / relative_path
        summary = json.loads((root / "real-llm-acceptance.json").read_text(encoding="utf-8"))
        assert summary["run_id"] == run_id
        assert summary["tested_code_sha"] == evidence["tested_code_sha"]
        assert summary["passed"] == 6 and summary["scenario_count"] == 6
        result = subprocess.run(
            [
                sys.executable,
                str(EVIDENCE_VERIFIER),
                "--artifact-dir",
                str(root),
                "--expected-sha",
                evidence["tested_code_sha"],
                "--compact",
            ],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_done_tasks_have_complete_evidence() -> None:
    state = _load_state()
    for task_id, task in state["tasks"].items():
        if task["status"] == "done":
            assert task["tests_run"], (
                f"Task {task_id} is done but has empty tests_run; "
                "release evidence cannot be bypassed"
            )
            assert task.get("remaining") == [], (
                f"Task {task_id} is done but still names remaining work"
            )


def test_v7_5_2_scope_matches_r5_real_llm_release_state() -> None:
    scope = SCOPE_PATH.read_text(encoding="utf-8")
    lower_scope = scope.lower()

    assert "R5 scope" in scope
    assert "a07b9332ac0a11ef53bd4e9081b845c1073da445" in scope
    assert "real_llm_acceptance_harness" in scope
    assert "real_llm_no_mock_fallback_proof" in scope
    assert "manual verification" in scope
    assert "rc3_evidence_transaction" in scope
    assert "in_progress" in scope
    assert "v1.0.0-rc3" in scope
    assert "cross-windows/linux" in lower_scope
    assert "bbox" in lower_scope
