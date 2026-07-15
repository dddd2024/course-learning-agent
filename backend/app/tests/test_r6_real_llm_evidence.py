from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess


PROJECT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_DIR / "scripts" / "verify_real_llm_evidence.py"
ACCEPTANCE_SCRIPT_PATH = PROJECT_DIR / "scripts" / "verify_real_llm_acceptance.py"
SHA = "a" * 40
RUN_ID = "r6-fixture-a"
PROVIDER = "openai-compatible"
MODEL = "model-a"
BASE_URL_HOST = "https://provider.example"
SCENARIO_IDS = [
    "REAL-01-model-config",
    "REAL-02-knowledge-points",
    "REAL-03-chat-and-citations",
    "REAL-04-quiz-and-weak-point",
    "REAL-05-learning-plan",
    "REAL-06-material-overview",
]
RUN_TYPES = ["outline", "course_qa", "quiz", "planner", "material_overview"]
R6_EVIDENCE_ROOT = PROJECT_DIR / "docs" / "engineering" / "evidence" / "r6"
R6_TESTED_SHA = "7b7401b74833fb5fe0e187b396135fdf1c82399d"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_real_llm_evidence_r6", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_acceptance_writer():
    spec = importlib.util.spec_from_file_location("verify_real_llm_acceptance_r6", ACCEPTANCE_SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_bundle(root: Path) -> None:
    summary = {
        "schema_version": 1,
        "tested_code_sha": SHA,
        "run_id": RUN_ID,
        "provider": PROVIDER,
        "base_url_host": BASE_URL_HOST,
        "model": MODEL,
        "all_passed": True,
        "fallback_count": 0,
        "mock_count": 0,
        "degraded_count": 0,
        "meta_missing_count": 0,
        "repair_attempt_count": 0,
        "repair_success_count": 0,
        "llm_call_count": 5,
        "all_meta_observed": True,
        "scenario_count": 6,
        "passed": 6,
        "failed": 0,
        "secret_scan": {"status": "passed", "matches": 0},
    }
    scenarios = [{"id": scenario_id, "status": "passed"} for scenario_id in SCENARIO_IDS]
    runs = [
        {
            "run_type": run_type,
            "status": "success",
            "actual_provider": "user",
            "actual_model": MODEL,
            "meta_observed": True,
            "fallback_used": False,
            "repair_attempted": False,
            "repair_success": False,
            "llm_call_count": 1,
        }
        for run_type in RUN_TYPES
    ]
    values = {
        "real-llm-acceptance.json": summary,
        "scenario-results.json": scenarios,
        "redacted-agent-runs.json": runs,
        "environment-fingerprint.json": {
            "python": "3.11.9",
            "platform": "linux",
            "base_url_host": BASE_URL_HOST,
        },
        "request-summary.json": {"scenario_ids": SCENARIO_IDS, "failure": None},
    }
    for name, value in values.items():
        (root / name).write_text(json.dumps(value), encoding="utf-8")
    _write_manifest(root)


def _write_manifest(root: Path) -> None:
    summary = json.loads((root / "real-llm-acceptance.json").read_text(encoding="utf-8"))
    runs = json.loads((root / "redacted-agent-runs.json").read_text(encoding="utf-8"))
    files = {}
    for path in root.iterdir():
        if path.is_file() and path.name != "evidence-manifest.json":
            data = path.read_bytes()
            files[path.name] = {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {
        "schema_version": 1,
        "run_id": summary["run_id"],
        "tested_code_sha": summary["tested_code_sha"],
        "provider": summary["provider"],
        "base_url_host": summary["base_url_host"],
        "model": summary["model"],
        "scenario_count": summary["scenario_count"],
        "passed": summary["passed"],
        "audited_agent_run_count": len(runs),
        "fallback_count": summary["fallback_count"],
        "mock_count": summary["mock_count"],
        "degraded_count": summary["degraded_count"],
        "meta_missing_count": summary["meta_missing_count"],
        "secret_scan_status": summary["secret_scan"]["status"],
        "files": files,
    }
    (root / "evidence-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _rewrite_json(path: Path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_valid_bundle_passes(tmp_path: Path) -> None:
    verifier = _load_verifier()
    _write_bundle(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) is None


def test_tampering_or_file_set_changes_fail(tmp_path: Path) -> None:
    verifier = _load_verifier()
    _write_bundle(tmp_path)
    (tmp_path / "scenario-results.json").write_text("[]", encoding="utf-8")
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "HASH_MISMATCH"

    _write_bundle(tmp_path)
    (tmp_path / "extra.json").write_text("{}", encoding="utf-8")
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "FILE_SET_MISMATCH"


def test_missing_or_wrong_contract_data_fails(tmp_path: Path) -> None:
    verifier = _load_verifier()
    _write_bundle(tmp_path)
    (tmp_path / "redacted-agent-runs.json").unlink()
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "REQUIRED_ARTIFACT_INVALID"

    _write_bundle(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, "b" * 40) == "SHA_MISMATCH"


def test_null_fallback_wrong_scenario_or_run_count_fail(tmp_path: Path) -> None:
    verifier = _load_verifier()
    _write_bundle(tmp_path)
    runs_path = tmp_path / "redacted-agent-runs.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8"))
    runs[0]["fallback_used"] = None
    _rewrite_json(runs_path, runs)
    _write_manifest(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "RUN_CONTRACT_FAILED"

    _write_bundle(tmp_path)
    scenarios_path = tmp_path / "scenario-results.json"
    _rewrite_json(scenarios_path, [{"id": scenario_id, "status": "passed"} for scenario_id in SCENARIO_IDS[:-1]])
    _write_manifest(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "SCENARIO_CONTRACT_FAILED"

    _write_bundle(tmp_path)
    runs = json.loads(runs_path.read_text(encoding="utf-8"))[:-1]
    _rewrite_json(runs_path, runs)
    _write_manifest(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "RUN_CONTRACT_FAILED"


def test_manifest_and_request_fields_are_cross_checked(tmp_path: Path) -> None:
    verifier = _load_verifier()
    _write_bundle(tmp_path)
    manifest_path = tmp_path / "evidence-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provider"] = "different-provider"
    _rewrite_json(manifest_path, manifest)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "MANIFEST_CONTRACT_FAILED"

    _write_bundle(tmp_path)
    request_path = tmp_path / "request-summary.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["failure"] = {"error": "hidden failure"}
    _rewrite_json(request_path, request)
    _write_manifest(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "REQUEST_CONTRACT_FAILED"


def test_provider_model_and_count_forgery_fail(tmp_path: Path) -> None:
    verifier = _load_verifier()
    _write_bundle(tmp_path)
    runs_path = tmp_path / "redacted-agent-runs.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8"))
    runs[0]["actual_provider"] = "mock"
    _rewrite_json(runs_path, runs)
    _write_manifest(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "RUN_CONTRACT_FAILED"

    _write_bundle(tmp_path)
    summary_path = tmp_path / "real-llm-acceptance.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["llm_call_count"] = 99
    _rewrite_json(summary_path, summary)
    _write_manifest(tmp_path)
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "STRICT_COUNTS_FAILED"


def test_r6_bundles_use_lf_checkout_and_preserve_manifest_bytes(tmp_path: Path) -> None:
    """R6 manifests intentionally verify raw bytes; CRLF must remain detectable."""
    verifier = _load_verifier()
    paths = [
        R6_EVIDENCE_ROOT / run_id / "real-llm-acceptance.json"
        for run_id in ("r6-c1-a", "r6-c1-b")
    ]
    attrs = subprocess.run(
        ["git", "check-attr", "eol", "--", *(str(path.relative_to(PROJECT_DIR)) for path in paths)],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert attrs and all(line.endswith(": lf") for line in attrs)

    for run_id in ("r6-c1-a", "r6-c1-b"):
        root = R6_EVIDENCE_ROOT / run_id
        assert verifier.verify_evidence_bundle(root, R6_TESTED_SHA) is None

        tampered = tmp_path / run_id
        shutil.copytree(root, tampered)
        manifest = json.loads((tampered / "evidence-manifest.json").read_text(encoding="utf-8"))
        for name in manifest["files"]:
            path = tampered / name
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        assert verifier.verify_evidence_bundle(tampered, R6_TESTED_SHA) == "HASH_MISMATCH"


def test_acceptance_writer_emits_deterministic_lf_bundle_bytes(tmp_path: Path) -> None:
    """Generated evidence is hashed as-written, with no verifier normalization."""
    writer = _load_acceptance_writer()
    verifier = _load_verifier()
    summary = {
        "schema_version": 1,
        "tested_code_sha": SHA,
        "run_id": RUN_ID,
        "provider": PROVIDER,
        "base_url_host": BASE_URL_HOST,
        "model": MODEL,
        "all_passed": True,
        "fallback_count": 0,
        "mock_count": 0,
        "degraded_count": 0,
        "meta_missing_count": 0,
        "repair_attempt_count": 0,
        "repair_success_count": 0,
        "llm_call_count": 5,
        "all_meta_observed": True,
        "scenario_count": 6,
        "passed": 6,
        "failed": 0,
        "secret_scan": {"status": "passed", "matches": 0},
    }
    scenarios = [{"id": scenario_id, "status": "passed"} for scenario_id in SCENARIO_IDS]
    runs = [
        {
            "run_type": run_type,
            "status": "success",
            "actual_provider": "user",
            "actual_model": MODEL,
            "meta_observed": True,
            "fallback_used": False,
            "repair_attempted": False,
            "repair_success": False,
            "llm_call_count": 1,
        }
        for run_type in RUN_TYPES
    ]
    values = {
        "real-llm-acceptance.json": summary,
        "scenario-results.json": scenarios,
        "redacted-agent-runs.json": runs,
        "environment-fingerprint.json": {"python": "3.11.9", "platform": "win32", "base_url_host": BASE_URL_HOST},
        "request-summary.json": {"scenario_ids": SCENARIO_IDS, "failure": None},
    }
    for name, value in values.items():
        writer._json_path(tmp_path / name, value)
    writer._write_evidence_manifest(tmp_path, summary, runs)

    for path in tmp_path.glob("*.json"):
        raw = path.read_bytes()
        assert b"\r\n" not in raw
        assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
        assert not raw.startswith(b"\xef\xbb\xbf")
        raw.decode("utf-8")

    manifest = json.loads((tmp_path / "evidence-manifest.json").read_text(encoding="utf-8"))
    for name, recorded in manifest["files"].items():
        raw = (tmp_path / name).read_bytes()
        assert recorded == {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    assert verifier.verify_evidence_bundle(tmp_path, SHA) is None

    tampered = tmp_path / "scenario-results.json"
    tampered.write_bytes(tampered.read_bytes().replace(b"\n", b"\r\n"))
    assert verifier.verify_evidence_bundle(tmp_path, SHA) == "HASH_MISMATCH"
