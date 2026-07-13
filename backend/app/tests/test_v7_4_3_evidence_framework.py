"""Behavioral tests for the V7.4.3 local evidence contract."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
COLLECTOR = PROJECT_DIR / "scripts" / "collect_local_evidence.py"
VERIFIER = PROJECT_DIR / "scripts" / "verify_local_evidence.py"


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_DIR, text=True).strip()


def make_manifest(tmp_path: Path, command: list[str] | None = None) -> Path:
    fixture = tmp_path / "fixture.txt"
    fixture.write_text("evidence fixture", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    config = {
        "base_sha": git_head(),
        "head_sha": git_head(),
        "output": str(manifest),
        "include": [str(fixture)],
        "commands": [{"label": "probe", "command": command or [sys.executable, "-c", "print('probe ok')"]}],
    }
    config_path = tmp_path / "run-plan.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    result = subprocess.run([sys.executable, str(COLLECTOR), "--config", str(config_path)], cwd=PROJECT_DIR, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return manifest


def run_verifier(manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(VERIFIER), str(manifest)], cwd=PROJECT_DIR, capture_output=True, text=True)


def test_state_resets_false_v7_4_2_closure():
    state = json.loads((PROJECT_DIR / "docs/engineering/v7-execution-state.json").read_text(encoding="utf-8"))
    assert state["version"] == "v7.4.4"
    assert state["overall_status"] in {"in_progress", "verified_locally"}
    if state["overall_status"] == "in_progress":
        assert state["local_closure"] is None
    else:
        assert state["current_task"] is None
        assert state["local_closure"] == "V7.4.3_FUNCTIONALLY_CLOSED_LOCALLY"
    for task in state["tasks"].values():
        assert {"status", "changed_files", "commands", "tests_run", "evidence", "remaining", "next_task", "commits"} <= task.keys()


def test_collector_saves_raw_streams_and_hashes(tmp_path: Path):
    manifest = make_manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    record = data["commands"][0]
    assert Path(record["stdout_log_path"]).read_text(encoding="utf-8") == "probe ok\n"
    assert Path(record["stderr_log_path"]).read_text(encoding="utf-8") == ""
    assert len(record["stdout_log_sha256"]) == 64
    assert data["files"]


def test_collector_decodes_utf8_command_output(tmp_path: Path):
    manifest = make_manifest(
        tmp_path,
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write('验证'.encode('utf-8'))"],
    )
    record = json.loads(manifest.read_text(encoding="utf-8"))["commands"][0]
    assert "验证" in Path(record["stdout_log_path"]).read_text(encoding="utf-8")


def test_valid_manifest_verifies(tmp_path: Path):
    result = run_verifier(make_manifest(tmp_path))
    assert result.returncode == 0, result.stderr


def test_missing_log_fails_verification(tmp_path: Path):
    manifest = make_manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    Path(data["commands"][0]["stdout_log_path"]).unlink()
    assert run_verifier(manifest).returncode == 1


def test_bad_exit_code_fails_verification(tmp_path: Path):
    manifest = make_manifest(tmp_path, [sys.executable, "-c", "import sys; sys.exit(7)"])
    assert run_verifier(manifest).returncode == 1


def test_tampered_manifest_file_hash_and_head_fail(tmp_path: Path):
    manifest = make_manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["head_sha"] = "0" * 40
    data["files"][0]["sha256"] = "f" * 64
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert run_verifier(manifest).returncode == 1
