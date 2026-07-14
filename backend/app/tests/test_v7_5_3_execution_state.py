"""State-contract tests for the V7.5.3 audit-closure round."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
SCOPE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-3-scope.md"
REVIEW_ONLY_MARKERS = {"review", "manual review", "config review", "inspection"}


def _state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_DIR, text=True, encoding="utf-8"
    ).strip()


def test_v7_5_3_is_honestly_reopened_until_executable_evidence_exists() -> None:
    state = _state()
    assert state["version"] == "v7.5.3"
    assert state["base_commit"] == "b7facf8b891468010d88cf171497934763a12b77"
    assert state["branch"] == "codex/v7-5-3-rc3-audit-closure"

    if state["overall_status"] == "in_progress":
        assert state["current_task"] in state["tasks"]
        assert state["local_closure"] is None
        assert state["release_candidate"] is None
        assert state["closure_evidence"] is None
        for blocker in (
            "e2e_real_service_reuse",
            "e2e_non_unique_environment",
            "page_asset_recovery_outside_lock",
            "page_asset_recovery_db_fs_ambiguity",
            "page_asset_lock_ownership",
            "missing_executed_e2e_evidence",
        ):
            assert blocker in state["audit_blockers"]
    else:
        assert state["overall_status"] == "verified_locally"
        assert state["audit_blockers"] == []
        assert state["current_task"] is None
        assert state["local_closure"] == "V7.5.3_AUDIT_BLOCKERS_CLOSED_LOCALLY"
        assert state["release_candidate"] == "v1.0.0-rc4"


def test_done_tasks_cannot_use_review_text_as_test_evidence() -> None:
    state = _state()
    for task_id, task in state["tasks"].items():
        if task["status"] != "done" or not task["tests_run"]:
            continue
        for entry in task["tests_run"]:
            text = entry if isinstance(entry, str) else json.dumps(entry, ensure_ascii=False)
            assert text.strip().lower() not in REVIEW_ONLY_MARKERS, (
                f"{task_id} uses review-only text as executable evidence"
            )


def test_verified_state_requires_sha_bound_release_gate() -> None:
    state = _state()
    if state["overall_status"] != "verified_locally":
        return

    evidence = state["closure_evidence"]
    assert isinstance(evidence, dict)
    relative_path = evidence["result_path"]
    result_path = PROJECT_DIR / relative_path
    assert result_path.is_file()

    raw = result_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == evidence["sha256"]
    result = json.loads(raw)
    assert result["passed"] is True
    assert result["tested_sha"] == _head()
    assert result["final_sha"] == _head()
    assert result["head_unchanged"] is True
    assert result["dirty_before"] is False
    assert result["dirty_after"] is False
    assert result["e2e"]["passed"] == 6
    assert result["e2e"]["failed"] == 0
    assert result["teardown"]["passed"] is True
    assert result["normal_uploads_unchanged"] is True
    assert all(step["exit_code"] == 0 for step in result["steps"])


def test_scope_records_all_audit_findings_and_deferrals() -> None:
    scope = SCOPE_PATH.read_text(encoding="utf-8")
    for marker in (
        "e2e_real_service_reuse",
        "e2e_non_unique_environment",
        "page_asset_recovery_outside_lock",
        "page_asset_recovery_db_fs_ambiguity",
        "page_asset_lock_ownership",
        "missing_executed_e2e_evidence",
        "NULL",
        "PageCanvas",
        "remote",
        "v1.0.0-rc4",
    ):
        assert marker.lower() in scope.lower()
