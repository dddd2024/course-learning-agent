#!/usr/bin/env python
"""V7 Function Closure Verification Script.

Replaces the V6 gate. Runs all V7 verification checks (which include
V6 backward-compat checks) and produces a machine-readable JSON report.

Exit code 0 only if ALL checks pass with no failures and no critical skips.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURE_DIR = BACKEND_DIR / "app" / "tests" / "fixtures" / "course_materials"

PASS_RE = re.compile(r"(\d+) passed")
FAIL_RE = re.compile(r"(\d+) failed")
SKIP_RE = re.compile(r"(\d+) skipped")
ERROR_RE = re.compile(r"(\d+) error")

CHECKS = []


def register_check(name: str, category: str):
    def decorator(fn):
        CHECKS.append({"name": name, "category": category, "fn": fn})
        return fn
    return decorator


def run_command(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> tuple[int, str]:
    merged_env = os.environ.copy()
    merged_env["LLM_PROVIDER"] = "mock"
    merged_env["PYTHONPATH"] = str(BACKEND_DIR)
    if env:
        merged_env.update(env)
    result = subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=merged_env,
        timeout=300,
    )
    output = result.stdout + result.stderr
    return result.returncode, output


def parse_pytest_output(output: str) -> dict:
    passed = failed = skipped = errors = 0
    m = PASS_RE.search(output)
    if m:
        passed = int(m.group(1))
    m = FAIL_RE.search(output)
    if m:
        failed = int(m.group(1))
    m = SKIP_RE.search(output)
    if m:
        skipped = int(m.group(1))
    m = ERROR_RE.search(output)
    if m:
        errors = int(m.group(1))
    return {"passed": passed, "failed": failed, "skipped": skipped, "errors": errors}


def _run_pytest(test_path: str) -> tuple[bool, str, dict]:
    """Helper: run a pytest file and return (passed, output, stats)."""
    cmd = [sys.executable, "-m", "pytest", test_path, "-q"]
    code, output = run_command(cmd, cwd=BACKEND_DIR)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


# ---------------------------------------------------------------------------
# V6 backward-compat checks
# ---------------------------------------------------------------------------

@register_check("backend_schema", "backend")
def check_backend_schema():
    cmd = [sys.executable, "-c",
           "from app.models.base import Base; from sqlalchemy import create_engine; "
           "e = create_engine('sqlite:///:memory:'); Base.metadata.create_all(e); print('OK')"]
    code, output = run_command(cmd, cwd=BACKEND_DIR)
    return code == 0 and "OK" in output, output


@register_check("migration_dry_run", "backend")
def check_migration():
    cmd = [sys.executable, str(SCRIPTS_DIR / "migrate.py"), "--dry-run"]
    code, output = run_command(cmd)
    return code == 0, output


@register_check("backend_tests", "backend")
def check_backend_tests():
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests"), "-q"]
    code, output = run_command(cmd, cwd=BACKEND_DIR)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0 and stats["skipped"] == 0, output, stats


@register_check("v6_task_flows", "backend")
def check_v6_tasks():
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v6_task_flows.py"))


@register_check("v6_multi_plan", "backend")
def check_v6_multi_plan():
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v6_multi_plan.py"))


@register_check("v6_quiz_constraints", "backend")
def check_v6_quiz():
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v6_quiz_constraints.py"))


@register_check("v6_parse_worker", "backend")
def check_v6_worker():
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v6_parse_worker.py"))


@register_check("v6_fixtures", "backend")
def check_v6_fixtures():
    expected = {
        "networking-two-column.pdf": "aa4212429ae6e980",
        "operating-system-slides.pptx": "9fce6b581ffc621c",
        "image-heavy-course.pdf": "ba55a2ec5786d4e2",
        "corrupted-sample.pdf": "b4f935ec81e55df1",
    }
    results = []
    for name, prefix in expected.items():
        path = FIXTURE_DIR / name
        if not path.exists():
            results.append(f"MISSING: {name}")
            continue
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        if not h.startswith(prefix):
            results.append(f"HASH_MISMATCH: {name} expected {prefix}... got {h[:16]}...")
        else:
            results.append(f"OK: {name}")
    all_ok = all(r.startswith("OK") for r in results)
    return all_ok, "\n".join(results)


# ---------------------------------------------------------------------------
# V7 checks
# ---------------------------------------------------------------------------

@register_check("v7_3_01_cleaned_chunk_pipeline", "backend")
def check_v7_cleaned_chunk_pipeline():
    """V7.3-01: Document cleaning pipeline feeds cleaned IR to chunker."""
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v7_3_cleaned_chunk_pipeline.py"))


@register_check("v7_3_01_chunk_provenance", "backend")
def check_v7_chunk_provenance():
    """V7.3-01: Chunk source fragment provenance tracking."""
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v7_3_chunk_fragment_provenance.py"))


@register_check("v7_3_01_page_migration", "backend")
def check_v7_page_migration():
    """V7.3-01: Page version unique constraint migration."""
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v7_3_page_upgrade_migration.py"))


@register_check("v7_3_02_unified_quiz", "backend")
def check_v7_unified_quiz():
    """V7.3-02: Unified quiz creation with strict contract."""
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v7_3_unified_quiz_creation.py"))


@register_check("v7_3_03_multi_plan_lifecycle", "backend")
def check_v7_multi_plan_lifecycle():
    """V7.3-03: Multi-plan persistence lifecycle."""
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v7_3_multi_plan_lifecycle.py"))


# ---------------------------------------------------------------------------
# Frontend checks
# ---------------------------------------------------------------------------

@register_check("frontend_type_check", "frontend")
def check_frontend_type():
    cmd = ["npm.cmd" if os.name == "nt" else "npm", "run", "type-check"]
    code, output = run_command(cmd, cwd=FRONTEND_DIR)
    return code == 0, output


@register_check("frontend_unit", "frontend")
def check_frontend_unit():
    cmd = ["npm.cmd" if os.name == "nt" else "npm", "run", "test", "--", "--run"]
    code, output = run_command(cmd, cwd=FRONTEND_DIR)
    return code == 0, output


@register_check("frontend_build", "frontend")
def check_frontend_build():
    cmd = ["npm.cmd" if os.name == "nt" else "npm", "run", "build"]
    code, output = run_command(cmd, cwd=FRONTEND_DIR)
    return code == 0, output


# ---------------------------------------------------------------------------
# E2E checks (V7: verify 11 scenarios exist and pass)
# ---------------------------------------------------------------------------

V7_E2E_IDS = [f"V7-E2E-{i:02d}" for i in range(1, 12)]


@register_check("v7_e2e_scenarios", "e2e")
def check_v7_e2e(external_report: Path | None = None):
    """Verify all 11 V7-E2E scenarios exist and passed in the Playwright report."""
    if external_report:
        report_path = external_report
    else:
        report_path = FRONTEND_DIR / "playwright-results.json"

    if not report_path.exists():
        return False, f"Report not found: {report_path}"

    data = json.loads(report_path.read_text(encoding="utf-8"))

    # Collect all test titles from the report
    all_titles: list[str] = []

    def collect_titles(nodes):
        for node in nodes:
            title = node.get("title", "")
            all_titles.append(title)
            collect_titles(node.get("specs", []))
            collect_titles(node.get("suites", []))

    for suite in data.get("suites", []):
        collect_titles([suite])

    # Also check top-level specs
    collect_titles(data.get("specs", []))

    # Check each V7-E2E scenario
    missing = []
    for eid in V7_E2E_IDS:
        found = any(eid in title for title in all_titles)
        if not found:
            missing.append(eid)

    if missing:
        return False, f"Missing V7 E2E scenarios: {', '.join(missing)}"

    # Check overall stats
    stats = data.get("stats", {})
    failed = int(stats.get("unexpected", 0))
    skipped = int(stats.get("skipped", 0))

    if failed > 0 or skipped > 0:
        return False, f"E2E has failures: failed={failed}, skipped={skipped}"

    return True, f"All {len(V7_E2E_IDS)} V7 E2E scenarios passed"


@register_check("e2e", "e2e")
def check_e2e(external_report: Path | None = None):
    """Run or validate Playwright E2E tests (backward compat)."""
    if external_report:
        if external_report.exists():
            data = json.loads(external_report.read_text(encoding="utf-8"))
            stats = data.get("stats", {})
            failed = stats.get("unexpected", 0)
            return failed == 0, str(external_report)
        return False, f"Report not found: {external_report}"
    cmd = ["npx", "playwright", "test", "--reporter=json"]
    code, output = run_command(cmd, cwd=FRONTEND_DIR, env={"CI": "true"})
    return code == 0, output


def main():
    parser = argparse.ArgumentParser(description="V7 Function Closure Verification")
    parser.add_argument("--artifact-root", default="artifacts", help="Artifact output root")
    parser.add_argument("--external-e2e", type=Path, default=None, help="Pre-produced E2E report")
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_root) / "verification" / "v7"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True
    ).stdout.strip()

    results = []
    all_passed = True

    for check in CHECKS:
        name = check["name"]
        category = check["category"]
        print(f"Running {name}...", flush=True)
        try:
            if name in ("e2e", "v7_e2e_scenarios") and args.external_e2e:
                result = check["fn"](args.external_e2e)
            else:
                result = check["fn"]()

            if isinstance(result, tuple) and len(result) == 3:
                passed, output, stats = result
            elif isinstance(result, tuple) and len(result) == 2:
                passed, output = result
                stats = {}
            else:
                passed = bool(result)
                output = str(result)
                stats = {}

            status = "pass" if passed else "fail"
            if not passed:
                all_passed = False
        except Exception as e:
            status = "error"
            output = str(e)
            stats = {}
            passed = False
            all_passed = False

        entry = {
            "name": name,
            "category": category,
            "status": status,
            "output_preview": output[:500] if isinstance(output, str) else str(output)[:500],
            "stats": stats if stats else {},
        }
        results.append(entry)
        print(f"  -> {status}", flush=True)

    report = {
        "version": "v7",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha,
        "total_checks": len(results),
        "passed_checks": sum(1 for r in results if r["status"] == "pass"),
        "failed_checks": sum(1 for r in results if r["status"] != "pass"),
        "all_passed": all_passed,
        "v7_e2e_scenarios": V7_E2E_IDS,
        "checks": results,
    }

    report_path = artifact_dir / "v7-acceptance.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Also write to the root for CI backward compat
    root_report = Path(args.artifact_root) / "verification-result.json"
    root_report.parent.mkdir(parents=True, exist_ok=True)
    with open(root_report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nReport saved to: {report_path}")
    print(f"Total: {report['total_checks']}, Passed: {report['passed_checks']}, Failed: {report['failed_checks']}")

    if all_passed:
        print("ALL V7 CHECKS PASSED")
    else:
        print("SOME V7 CHECKS FAILED")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
