"""Machine-readable V7 acceptance gate.

The gate is deliberately scenario-aware: a green Playwright command is not
enough unless every required V7 scenario appears as a passed test result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_SCENARIOS = {f"V7-E2E-{number:02d}" for number in range(1, 12)}
ROOT = Path(__file__).resolve().parent.parent

def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)

def _scenario_results(report: dict) -> tuple[set[str], list[str]]:
    passed, failures = set(), []
    for node in _walk(report):
        title = str(node.get("title", ""))
        scenario = next((item for item in REQUIRED_SCENARIOS if item in title), None)
        if not scenario:
            continue
        results = node.get("results", [])
        statuses = [str(result.get("status")) for result in results if isinstance(result, dict)]
        if statuses and all(status == "passed" for status in statuses):
            passed.add(scenario)
        elif statuses:
            failures.append(f"{scenario}:{','.join(statuses)}")
    return passed, failures

def _run_test(path: str) -> dict:
    result = subprocess.run(["python", "-m", "pytest", path, "-q"], cwd=ROOT, text=True, capture_output=True)
    return {"name": path, "status": "pass" if result.returncode == 0 else "fail", "output": (result.stdout + result.stderr)[-4000:]}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", default="artifacts/v7")
    parser.add_argument("--external-e2e", required=True)
    args = parser.parse_args()
    checks = [_run_test("backend/app/tests/test_v7_document_ir_pipeline.py"), _run_test("backend/app/tests/test_v7_learn_evidence.py")]
    e2e_path = Path(args.external_e2e)
    observed, scenario_errors = set(), ["playwright JSON missing"]
    if e2e_path.exists():
        observed, scenario_errors = _scenario_results(json.loads(e2e_path.read_text(encoding="utf-8")))
    missing = sorted(REQUIRED_SCENARIOS - observed)
    checks.append({"name": "required_v7_scenarios", "status": "pass" if not missing and not scenario_errors else "fail", "missing": missing, "errors": scenario_errors})
    fixture_hashes = {}
    for fixture in ROOT.glob("**/networking-two-column.pdf"):
        fixture_hashes[str(fixture.relative_to(ROOT))] = hashlib.sha256(fixture.read_bytes()).hexdigest()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = {"version": "v7", "commit_sha": sha, "base_commit": "53a1221c31909d7069543a4bc703240175cec125", "generated_at": datetime.now(timezone.utc).isoformat(), "checks": checks, "required_scenarios": sorted(REQUIRED_SCENARIOS), "observed_scenarios": sorted(observed), "fixture_hashes": fixture_hashes, "all_passed": all(item["status"] == "pass" for item in checks)}
    target = Path(args.artifact_root) / "v7-acceptance.json"; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
