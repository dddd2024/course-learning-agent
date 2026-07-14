from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_DIR / "scripts" / "verify_real_llm_evidence.py"
SHA = "a" * 40


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_real_llm_evidence_r6", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_bundle(root: Path) -> None:
    summary = {
        "tested_code_sha": SHA, "all_passed": True, "scenario_count": 6, "passed": 6,
        "fallback_count": 0, "mock_count": 0, "degraded_count": 0, "meta_missing_count": 0,
        "secret_scan": {"status": "passed"},
    }
    scenarios = [{"id": f"REAL-{index}", "status": "passed"} for index in range(1, 7)]
    runs = [{"status": "success", "meta_observed": True, "fallback_used": False} for _ in range(5)]
    for name, value in (("real-llm-acceptance.json", summary), ("scenario-results.json", scenarios), ("redacted-agent-runs.json", runs)):
        (root / name).write_text(json.dumps(value), encoding="utf-8")
    _write_manifest(root)


def _write_manifest(root: Path) -> None:
    files = {}
    for path in root.iterdir():
        if path.is_file() and path.name != "evidence-manifest.json":
            data = path.read_bytes()
            files[path.name] = {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (root / "evidence-manifest.json").write_text(json.dumps({"tested_code_sha": SHA, "files": files}), encoding="utf-8")


def test_valid_bundle_passes(tmp_path: Path) -> None:
    verifier = _load_verifier(); _write_bundle(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) is None


def test_tampering_or_file_set_changes_fail(tmp_path: Path) -> None:
    verifier = _load_verifier(); _write_bundle(tmp_path)
    (tmp_path / "scenario-results.json").write_text("[]", encoding="utf-8")
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "HASH_MISMATCH"
    _write_manifest(tmp_path)
    (tmp_path / "extra.json").write_text("{}", encoding="utf-8")
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "FILE_SET_MISMATCH"


def test_missing_or_wrong_contract_data_fails(tmp_path: Path) -> None:
    verifier = _load_verifier(); _write_bundle(tmp_path)
    (tmp_path / "redacted-agent-runs.json").unlink()
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "REQUIRED_ARTIFACT_INVALID"
    _write_bundle(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, "b" * 40) == "SHA_MISMATCH"


def test_null_fallback_wrong_scenario_or_run_count_fail(tmp_path: Path) -> None:
    verifier = _load_verifier(); _write_bundle(tmp_path)
    runs_path = tmp_path / "redacted-agent-runs.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8")); runs[0]["fallback_used"] = None
    runs_path.write_text(json.dumps(runs), encoding="utf-8")
    _write_manifest(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "RUN_CONTRACT_FAILED"
    _write_bundle(tmp_path)
    scenarios_path = tmp_path / "scenario-results.json"
    scenarios_path.write_text(json.dumps([{ "status": "passed" }] * 5), encoding="utf-8")
    _write_manifest(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "SCENARIO_CONTRACT_FAILED"
