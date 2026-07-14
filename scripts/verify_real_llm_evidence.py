#!/usr/bin/env python
"""Verify a redacted real-LLM evidence bundle without network access."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_FILES = {
    "real-llm-acceptance.json",
    "scenario-results.json",
    "redacted-agent-runs.json",
    "environment-fingerprint.json",
    "request-summary.json",
}
EXPECTED_SCENARIO_IDS = [
    "REAL-01-model-config",
    "REAL-02-knowledge-points",
    "REAL-03-chat-and-citations",
    "REAL-04-quiz-and-weak-point",
    "REAL-05-learning-plan",
    "REAL-06-material-overview",
]
EXPECTED_RUN_TYPES = [
    "outline",
    "course_qa",
    "quiz",
    "planner",
    "material_overview",
]
STRICT_COUNT_KEYS = (
    "fallback_count",
    "mock_count",
    "degraded_count",
    "meta_missing_count",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_evidence_bundle(root: Path, expected_sha: str) -> str | None:
    """Return a stable failure code, or ``None`` when a bundle is valid."""
    manifest_path = root / "evidence-manifest.json"
    if not manifest_path.is_file():
        return "MANIFEST_MISSING"
    try:
        manifest = _load_json(manifest_path)
        summary = _load_json(root / "real-llm-acceptance.json")
        scenarios = _load_json(root / "scenario-results.json")
        runs = _load_json(root / "redacted-agent-runs.json")
        environment = _load_json(root / "environment-fingerprint.json")
        request_summary = _load_json(root / "request-summary.json")
    except (OSError, json.JSONDecodeError):
        return "REQUIRED_ARTIFACT_INVALID"

    if not all(isinstance(item, dict) for item in (manifest, summary, environment, request_summary)):
        return "REQUIRED_ARTIFACT_INVALID"
    if manifest.get("schema_version") != 1 or summary.get("schema_version") != 1:
        return "MANIFEST_CONTRACT_FAILED"
    if manifest.get("tested_code_sha") != expected_sha or summary.get("tested_code_sha") != expected_sha:
        return "SHA_MISMATCH"

    run_id = str(summary.get("run_id") or "").strip()
    provider = str(summary.get("provider") or "").strip()
    model = str(summary.get("model") or "").strip()
    base_url_host = str(summary.get("base_url_host") or "").strip()
    if (
        not run_id
        or not provider
        or not model
        or not base_url_host
        or manifest.get("run_id") != run_id
        or manifest.get("provider") != provider
        or manifest.get("model") != model
        or manifest.get("base_url_host") != base_url_host
    ):
        return "MANIFEST_CONTRACT_FAILED"

    files = manifest.get("files")
    if not isinstance(files, dict):
        return "MANIFEST_FILES_INVALID"
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "evidence-manifest.json"
    }
    if not REQUIRED_FILES.issubset(actual) or actual != set(files):
        return "FILE_SET_MISMATCH"
    for name, data in files.items():
        path = root / name
        if not isinstance(data, dict) or not path.is_file():
            return "HASH_MISMATCH"
        raw = path.read_bytes()
        if len(raw) != data.get("size_bytes") or hashlib.sha256(raw).hexdigest() != data.get("sha256"):
            return "HASH_MISMATCH"

    if not isinstance(scenarios, list):
        return "SCENARIO_CONTRACT_FAILED"
    scenario_ids = [item.get("id") if isinstance(item, dict) else None for item in scenarios]
    if (
        scenario_ids != EXPECTED_SCENARIO_IDS
        or any(not isinstance(item, dict) or item.get("status") != "passed" for item in scenarios)
        or not summary.get("all_passed")
        or summary.get("scenario_count") != len(EXPECTED_SCENARIO_IDS)
        or summary.get("passed") != len(EXPECTED_SCENARIO_IDS)
        or summary.get("failed") != 0
        or manifest.get("scenario_count") != summary.get("scenario_count")
        or manifest.get("passed") != summary.get("passed")
    ):
        return "SCENARIO_CONTRACT_FAILED"
    if request_summary.get("scenario_ids") != EXPECTED_SCENARIO_IDS or request_summary.get("failure") is not None:
        return "REQUEST_CONTRACT_FAILED"

    if not isinstance(runs, list):
        return "RUN_CONTRACT_FAILED"
    run_types = [run.get("run_type") if isinstance(run, dict) else None for run in runs]
    if run_types != EXPECTED_RUN_TYPES:
        return "RUN_CONTRACT_FAILED"
    for run in runs:
        if (
            not isinstance(run, dict)
            or run.get("status") != "success"
            or run.get("meta_observed") is not True
            or run.get("fallback_used") is not False
            or str(run.get("actual_provider") or "").strip() in {"", "mock", "unknown"}
            or str(run.get("actual_model") or "").strip() != model
            or not isinstance(run.get("llm_call_count"), int)
            or int(run.get("llm_call_count")) < 1
        ):
            return "RUN_CONTRACT_FAILED"

    if (
        any(summary.get(key) != 0 for key in STRICT_COUNT_KEYS)
        or summary.get("all_meta_observed") is not True
        or summary.get("secret_scan", {}).get("status") != "passed"
        or summary.get("secret_scan", {}).get("matches") != 0
        or manifest.get("audited_agent_run_count") != len(runs)
        or manifest.get("secret_scan_status") != "passed"
        or any(manifest.get(key) != summary.get(key) for key in STRICT_COUNT_KEYS)
        or summary.get("llm_call_count") != sum(run["llm_call_count"] for run in runs)
        or summary.get("repair_attempt_count") != sum(bool(run.get("repair_attempted")) for run in runs)
        or summary.get("repair_success_count") != sum(bool(run.get("repair_success")) for run in runs)
    ):
        return "STRICT_COUNTS_FAILED"

    if (
        not str(environment.get("python") or "").strip()
        or not str(environment.get("platform") or "").strip()
        or environment.get("base_url_host") != base_url_host
    ):
        return "ENVIRONMENT_CONTRACT_FAILED"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    failure = verify_evidence_bundle(Path(args.artifact_dir), args.expected_sha)
    if failure:
        print(failure)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
