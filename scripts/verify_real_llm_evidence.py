#!/usr/bin/env python
"""Verify a redacted real-LLM evidence bundle without network access."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED_FILES = {
    "real-llm-acceptance.json",
    "scenario-results.json",
    "redacted-agent-runs.json",
}


def verify_evidence_bundle(root: Path, expected_sha: str) -> str | None:
    """Return a stable failure code, or ``None`` when a bundle is valid."""
    manifest_path = root / "evidence-manifest.json"
    if not manifest_path.is_file():
        return "MANIFEST_MISSING"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        summary = json.loads((root / "real-llm-acceptance.json").read_text(encoding="utf-8"))
        scenarios = json.loads((root / "scenario-results.json").read_text(encoding="utf-8"))
        runs = json.loads((root / "redacted-agent-runs.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "REQUIRED_ARTIFACT_INVALID"
    if not isinstance(manifest, dict) or not isinstance(summary, dict):
        return "REQUIRED_ARTIFACT_INVALID"
    if manifest.get("tested_code_sha") != expected_sha or summary.get("tested_code_sha") != expected_sha:
        return "SHA_MISMATCH"
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
    if (
        not summary.get("all_passed")
        or summary.get("scenario_count") != 6
        or summary.get("passed") != 6
        or not isinstance(scenarios, list)
        or len(scenarios) != 6
        or any(not isinstance(item, dict) or item.get("status") != "passed" for item in scenarios)
    ):
        return "SCENARIO_CONTRACT_FAILED"
    if not isinstance(runs, list) or len(runs) != 5 or any(
        not isinstance(run, dict)
        or run.get("status") != "success"
        or run.get("meta_observed") is not True
        or run.get("fallback_used") is not False
        for run in runs
    ):
        return "RUN_CONTRACT_FAILED"
    if (
        any(summary.get(key) != 0 for key in ("fallback_count", "mock_count", "degraded_count", "meta_missing_count"))
        or summary.get("secret_scan", {}).get("status") != "passed"
    ):
        return "STRICT_COUNTS_FAILED"
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
