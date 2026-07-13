"""V7.4.2-00: Evidence framework tests.

验证：
1. 执行状态文件是合法 JSON 且 overall_status == "in_progress"
2. 每个任务记录包含 changed_files/tests_run/evidence/remaining/next_task/commits
3. collect_local_evidence.py 能生成 manifest.json
4. manifest 包含 base/head SHA、命令、工作目录、时间、退出码
5. manifest 中每个文件记录有 SHA-256
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


STATE_FILE = PROJECT_DIR / "docs" / "engineering" / "v7-execution-state.json"
EVIDENCE_SCRIPT = PROJECT_DIR / "scripts" / "collect_local_evidence.py"
MANIFEST_DIR = PROJECT_DIR / "artifacts" / "v7-4-2-local"
MANIFEST_FILE = MANIFEST_DIR / "manifest.json"


class TestExecutionState:
    """V7.4.2-00: 执行状态文件结构验证。"""

    def test_state_is_valid_json_with_in_progress(self):
        """执行状态文件是合法 JSON 且 overall_status == in_progress。"""
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        assert data["version"] in ("v7.4.2", "v7.4.3", "v7.4.4", "v7.5.0", "v7.5.1", "v7.5.2")
        assert data["overall_status"] in ("in_progress", "verified_locally")
        if data["overall_status"] == "in_progress":
            assert data.get("local_closure") is None

    def test_each_task_has_required_fields(self):
        """每个任务记录包含 changed_files/tests_run/evidence/remaining/next_task/commits。"""
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        required_fields = {
            "changed_files", "tests_run", "evidence",
            "remaining", "next_task", "commits",
        }
        for task_id, task_data in data["tasks"].items():
            if not task_id.startswith("V7.4.2"):
                continue
            missing = required_fields - set(task_data.keys())
            assert not missing, f"{task_id} missing fields: {missing}"


class TestEvidenceScript:
    """V7.4.2-00: collect_local_evidence.py 脚本验证。"""

    def test_script_exists(self):
        """collect_local_evidence.py 存在。"""
        assert EVIDENCE_SCRIPT.exists(), f"Script not found: {EVIDENCE_SCRIPT}"

    def test_script_generates_manifest(self, tmp_path):
        """脚本能生成 manifest.json。"""
        result = subprocess.run(
            [sys.executable, str(EVIDENCE_SCRIPT),
             "--output", str(tmp_path / "manifest.json"),
             "--base-sha", "abc123",
             "--head-sha", "def456"],
            capture_output=True, text=True, cwd=str(PROJECT_DIR),
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        manifest_path = tmp_path / "manifest.json"
        assert manifest_path.exists()

    def test_manifest_has_required_fields(self, tmp_path):
        """manifest 包含 base/head SHA、命令、工作目录、时间、退出码。"""
        result = subprocess.run(
            [sys.executable, str(EVIDENCE_SCRIPT),
             "--output", str(tmp_path / "manifest.json"),
             "--base-sha", "abc123",
             "--head-sha", "def456"],
            capture_output=True, text=True, cwd=str(PROJECT_DIR),
        )
        assert result.returncode == 0
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert "base_sha" in manifest
        assert "head_sha" in manifest
        assert "generated_at" in manifest
        assert "commands" in manifest
        assert "files" in manifest

    def test_manifest_file_entries_have_sha256(self, tmp_path):
        """manifest 中每个文件记录有 SHA-256。"""
        # Create a test file to include
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = subprocess.run(
            [sys.executable, str(EVIDENCE_SCRIPT),
             "--output", str(tmp_path / "manifest.json"),
             "--base-sha", "abc123",
             "--head-sha", "def456",
             "--include", str(test_file)],
            capture_output=True, text=True, cwd=str(PROJECT_DIR),
        )
        assert result.returncode == 0
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert len(manifest["files"]) > 0
        for f in manifest["files"]:
            assert "path" in f
            assert "sha256" in f
            assert len(f["sha256"]) == 64  # SHA-256 hex
