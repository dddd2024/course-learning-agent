"""State-contract tests for the V7.5.0 document-fidelity release round."""
from __future__ import annotations

import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
BASELINE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-0-document-quality-baseline.md"
SCOPE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-0-scope.md"


def test_v7_5_0_starts_from_an_honest_document_fidelity_baseline() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    assert state["version"] == "v7.5.0"
    assert state["base_commit"] == "63a2a176e891059023c4dd2bad630c5c9a0218bc"
    assert state["overall_status"] == "in_progress"
    assert state["current_task"] == "V7.5.0-01"
    assert state["local_closure"] is None
    assert state["release_candidate"] is None
    assert state["remote_ci"] == "deferred_to_v7_6"
    assert state["tasks"]["V7.5.0-00"]["status"] == "done"
    assert state["tasks"]["V7.5.0-01"]["status"] == "in_progress"
    assert "closure_evidence_not_reproducible" in state["audit_blockers"]
    assert "pdf_page_fidelity_unverified" in state["audit_blockers"]


def test_v7_5_0_baseline_records_fixed_document_quality_contract() -> None:
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    scope = SCOPE_PATH.read_text(encoding="utf-8")

    assert "40" in baseline
    assert "23" in baseline
    assert "page 9" in baseline
    assert "page coverage" in baseline
    assert "v1.0.0" in scope
