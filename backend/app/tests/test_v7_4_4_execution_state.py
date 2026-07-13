"""State-contract tests for the V7.4.4 candidate-closure round."""
from __future__ import annotations

import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
BASELINE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-4-4-audit-baseline.md"
SCOPE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-4-4-scope.md"

REQUIRED_TASK_FIELDS = {
    "status", "changed_files", "commands", "tests_run", "test_summaries",
    "evidence", "remaining", "next_task", "commits",
}


def test_v7_4_4_state_starts_honestly_in_progress() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    if state["version"] == "v7.5.0":
        assert state["overall_status"] in {"in_progress", "verified_locally"}
        assert state["tasks"]["V7.5.0-00"]["status"] == "done"
        if state["overall_status"] == "in_progress":
            assert state["current_task"] in state["tasks"]
            assert state["local_closure"] is None
        return

    if state["version"] == "v7.5.1":
        assert state["overall_status"] in {"in_progress", "verified_locally"}
        assert state["tasks"]["V7.5.1-00"]["status"] == "done"
        if state["overall_status"] == "in_progress":
            assert state["current_task"] in state["tasks"]
            assert state["local_closure"] is None
        return

    assert state["version"] in ('v7.4.4', 'v7.5.0', 'v7.5.1')
    assert state["base_commit"] == "9af524e9e1c7ff149256170931cf7fc9d766858e"
    assert state["overall_status"] == "in_progress"
    assert state["current_task"] in state["tasks"]
    assert state["local_closure"] is None
    assert state["release_candidate"] is None
    assert state["remote_ci"] == "deferred_to_v7_6"
    assert len(state["audit_blockers"]) == 8
    assert set(state["tasks"]) == {f"V7.4.4-{number:02d}" for number in range(9)}
    assert state["tasks"]["V7.4.4-00"]["status"] == "done"
    assert state["tasks"][state["current_task"]]["status"] == "in_progress"


def test_v7_4_4_task_records_are_complete_and_done_evidence_exists() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    for task_id, task in state["tasks"].items():
        if not task_id.startswith("V7.4.4"):
            continue
        assert REQUIRED_TASK_FIELDS <= task.keys()
        if task["status"] == "done":
            for evidence_path in task["evidence"]:
                assert (PROJECT_DIR / evidence_path).is_file(), evidence_path


def test_v7_4_4_baseline_and_scope_documents_exist() -> None:
    assert BASELINE_PATH.is_file()
    assert SCOPE_PATH.is_file()
    assert "v1.0.0-rc1" in BASELINE_PATH.read_text(encoding="utf-8")
    assert "Out of scope" in SCOPE_PATH.read_text(encoding="utf-8")
