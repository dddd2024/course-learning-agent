"""State-contract tests for the V7.5.0 document-fidelity release round."""
from __future__ import annotations

import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
BASELINE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-0-document-quality-baseline.md"
SCOPE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-0-scope.md"


def test_v7_5_0_records_an_honest_document_fidelity_state() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    assert state["version"] == "v7.5.0"
    assert state["base_commit"] == "63a2a176e891059023c4dd2bad630c5c9a0218bc"
    assert state["overall_status"] in {"in_progress", "verified_locally"}
    assert state["remote_ci"] == "deferred_to_v7_6"
    assert state["tasks"]["V7.5.0-00"]["status"] == "done"
    if state["overall_status"] == "in_progress":
        assert state["current_task"] in state["tasks"]
        assert state["tasks"][state["current_task"]]["status"] == "in_progress"
        assert state["local_closure"] is None
        assert "closure_evidence_not_reproducible" in state["audit_blockers"]
    else:
        assert state["current_task"] is None
        assert state["local_closure"] == "V7.5.0_DOCUMENT_FIDELITY_AND_RC_CLOSED_LOCALLY"
        assert state["release_candidate"] == "v1.0.0-rc1"


def test_v7_5_0_baseline_records_self_contained_document_quality_contract() -> None:
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    scope = SCOPE_PATH.read_text(encoding="utf-8")

    assert "self-contained" in baseline
    assert "runtime-generated" in scope
    assert "does not\nassume that a current course PDF exists" in baseline
    assert "vector" in baseline
    assert "embedded-bitmap" in baseline
    assert "multi-column" in baseline
    assert "scanned-page" in baseline
    assert "page coverage" in baseline
    assert "v1.0.0" in scope
