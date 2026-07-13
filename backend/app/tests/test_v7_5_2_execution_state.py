"""State-contract tests for the V7.5.2 RC blocker fix round."""
from __future__ import annotations

import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
SCOPE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-2-scope.md"


def test_v7_5_2_records_honest_in_progress_state() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    assert state["version"] == "v7.5.2"
    assert state["base_commit"] == "fd5198b63e25b869b3a31fb0e7178b9c02f3c294"

    if state["overall_status"] == "in_progress":
        assert state["local_closure"] is None
        assert state["release_candidate"] is None
        assert state["current_task"] in state["tasks"]
        # P0 blockers must be present while in_progress
        assert "new_version_image_binding" in state["audit_blockers"]
        assert "page_asset_expected_page_coverage" in state["audit_blockers"]
        assert "page_asset_db_fs_compensation" in state["audit_blockers"]
        assert "e2e_environment_isolation" in state["audit_blockers"]
    else:
        # verified_locally — only allowed when all blockers cleared
        assert state["local_closure"] == "V7.5.2_RC_BLOCKERS_CLOSED_LOCALLY"
        assert state["release_candidate"] == "v1.0.0-rc3"
        assert state["audit_blockers"] == []
        assert state["current_task"] is None


def test_v7_5_2_tests_run_not_bypassable() -> None:
    """The state must not allow verified_locally with empty tests_run."""
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if state["overall_status"] == "verified_locally":
        for task_id, task in state["tasks"].items():
            if task["status"] == "done":
                assert task["tests_run"], (
                    f"Task {task_id} is done but has empty tests_run — "
                    "cannot bypass gate evidence"
                )


def test_v7_5_2_scope_lists_p0_and_p1_issues() -> None:
    scope = SCOPE_PATH.read_text(encoding="utf-8")
    # P0 blockers
    assert "new_version_image_binding" in scope
    assert "page_asset_expected_page_coverage" in scope
    assert "page_asset_db_fs_compensation" in scope
    assert "e2e_environment_isolation" in scope
    # P1 issues
    assert "weak assertions" in scope.lower() or "E2E" in scope
    assert "corrupted" in scope.lower() or "NULL" in scope
    # Deferred
    assert "remote ci" in scope.lower()
    assert "bbox" in scope.lower()
    # Target
    assert "v1.0.0-rc3" in scope
