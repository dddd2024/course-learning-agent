"""State-contract tests for the V7.5.3 audit-closure round."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
SCOPE_PATH = PROJECT_DIR / "docs" / "engineering" / "v7-5-3-scope.md"


def _state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=PROJECT_DIR, text=True, encoding="utf-8"
    ).strip()


def _head() -> str:
    return _git("rev-parse", "HEAD")


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


def test_verified_tasks_require_executable_structured_evidence() -> None:
    state = _state()
    if state["overall_status"] != "verified_locally":
        return

    for task_id, task in state["tasks"].items():
        assert task["status"] == "done", f"{task_id} is not done"
        assert task["tests_run"], f"{task_id} has no executable evidence"
        for entry in task["tests_run"]:
            assert isinstance(entry, dict), f"{task_id} evidence must be structured"
            assert entry.get("command"), f"{task_id} evidence has no command"
            assert entry.get("exit_code") == 0, f"{task_id} command did not pass"
            description = json.dumps(entry, ensure_ascii=False).lower()
            assert "manual review" not in description
            assert "config review" not in description


def test_verified_state_requires_sha_bound_release_gate() -> None:
    state = _state()
    if state["overall_status"] != "verified_locally":
        return

    evidence = state["closure_evidence"]
    assert isinstance(evidence, dict)
    result_path = PROJECT_DIR / evidence["result_path"]
    assert result_path.is_file()

    raw = result_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == evidence["sha256"]
    result = json.loads(raw)
    assert result["passed"] is True
    assert result["tested_sha"] == result["final_sha"]
    assert result["head_unchanged"] is True
    assert result["dirty_before"] is False
    assert result["dirty_after"] is False
    assert result["e2e"] == {
        "passed": 6,
        "failed": 0,
        "flaky": 0,
        "skipped": 0,
    }
    assert result["teardown"]["passed"] is True
    assert result["teardown"]["cleanup_passed"] is True
    assert result["normal_uploads_unchanged"] is True
    assert all(step["exit_code"] == 0 for step in result["steps"])

    head = _head()
    tested_sha = result["tested_sha"]
    if tested_sha == head:
        assert evidence.get("closure_mode", "same_commit") == "same_commit"
        return

    # A machine-generated gate result cannot contain the SHA of a future commit
    # that adds that result. Permit exactly one post-test evidence-only commit:
    # its parent is the tested code SHA and its diff contains no production/test
    # code changes, only the execution state and the referenced evidence tree.
    assert evidence.get("closure_mode") == "evidence_only_commit"
    parent = _git("rev-parse", "HEAD^")
    assert parent == tested_sha
    changed = set(_git("diff", "--name-only", parent, head).splitlines())
    evidence_root = str(Path(evidence["result_path"]).parent).replace("\\", "/") + "/"
    allowed_exact = {"docs/engineering/v7-execution-state.json"}
    assert changed
    assert all(path in allowed_exact or path.startswith(evidence_root) for path in changed), (
        f"post-test closure commit changed non-evidence files: {sorted(changed)}"
    )


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
