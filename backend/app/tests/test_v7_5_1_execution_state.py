"""State-contract tests for the V7.5.1 V1.0 user-path closure round."""
from __future__ import annotations

import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
SCOPE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-1-scope.md"


def test_v7_5_1_records_honest_in_progress_state() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    assert state["version"] in {"v7.5.1", "v7.5.2"}

    if state["version"] == "v7.5.2":
        assert state["overall_status"] in {"in_progress", "verified_locally"}
        assert "V7.5.2-00" in state["tasks"]
        if state["overall_status"] == "in_progress":
            assert state["current_task"] in state["tasks"]
            assert state["local_closure"] is None
        return

    assert state["base_commit"] == "4eae324ff28fa66b45da0fd587e6f51d078edd9d"
    assert state["overall_status"] in {"in_progress", "verified_locally"}
    assert state["remote_ci"] == "deferred_to_v1_1"
    assert state["tasks"]["V7.5.1-00"]["status"] == "done"

    if state["overall_status"] == "in_progress":
        assert state["current_task"] in state["tasks"]
        assert state["local_closure"] is None
        assert state["release_candidate"] is None
        assert len(state["audit_blockers"]) > 0
    else:
        assert state["current_task"] is None
        assert state["local_closure"] == "V7.5.1_V1_USER_PATHS_CLOSED_LOCALLY"
        assert state["release_candidate"] == "v1.0.0-rc2"
        assert state["audit_blockers"] == []


def test_v7_5_1_scope_distinguishes_must_fix_from_deferred() -> None:
    scope = SCOPE_PATH.read_text(encoding="utf-8")

    # Must-fix items present
    assert "Existing PDFs upgraded without page images" in scope
    assert "Scanned / image-only PDFs" in scope
    assert "falsely reports" in scope
    assert "Non-PDF materials" in scope
    assert "Knowledge-point jump" in scope
    assert "Deleting a material" in scope
    assert "E2E upload directory" in scope

    # Deferred items present
    assert "remote ci" in scope.lower()
    assert "bbox" in scope.lower()
    assert "virtual scrolling" in scope.lower()
    assert "deprecation-warning" in scope.lower()

    # V1.0 target
    assert "v1.0.0-rc2" in scope
