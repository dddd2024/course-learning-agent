#!/usr/bin/env python
"""V6 Function Closure Verification Script.

Runs all V6 verification checks and produces a machine-readable JSON report.
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
import tempfile
from pathlib import Path
from datetime import datetime, timezone

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


@register_check("backend_schema", "backend")
def check_backend_schema():
    """Verify all tables can be created from models."""
    cmd = [sys.executable, "-c",
           "from app.models.base import Base; from sqlalchemy import create_engine; "
           "e = create_engine('sqlite:///:memory:'); Base.metadata.create_all(e); print('OK')"]
    code, output = run_command(cmd, cwd=BACKEND_DIR)
    return code == 0 and "OK" in output, output


@register_check("migration_dry_run", "backend")
def check_migration():
    """Run migration dry-run."""
    cmd = [sys.executable, str(SCRIPTS_DIR / "migrate.py"), "--dry-run", "--json"]
    code, output = run_command(cmd)
    return code == 0, output


@register_check("backend_tests", "backend")
def check_backend_tests():
    """Run full backend pytest suite."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0 and stats["skipped"] == 0, output, stats


@register_check("v6_pdf_layout", "backend")
def check_v6_pdf_layout():
    """V6 PDF document layout tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_pdf_layout.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_kp_titles", "backend")
def check_v6_kp_titles():
    """V6 knowledge point title tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_kp_titles.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_pptx_layout", "backend")
def check_v6_pptx():
    """V6 PPTX layout tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_pptx_layout.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_semantic_chunk", "backend")
def check_v6_chunk():
    """V6 semantic chunker tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_semantic_chunk.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_cleaning", "backend")
def check_v6_cleaning():
    """V6 cleaning rules tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_cleaning.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_state_machine", "backend")
def check_v6_state_machine():
    """V6 task state machine tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_state_machine.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_task_flows", "backend")
def check_v6_tasks():
    """V6 task flow tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_task_flows.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_quiz_constraints", "backend")
def check_v6_quiz():
    """V6 quiz constraint tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_quiz_constraints.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_multi_plan", "backend")
def check_v6_multi_plan():
    """V6 multi-course plan lifecycle tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_multi_plan.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_parse_worker", "backend")
def check_v6_worker():
    """V6 parse worker tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_parse_worker.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_fts_index", "backend")
def check_v6_fts():
    """V6 FTS incremental index tests."""
    cmd = [sys.executable, "-m", "pytest", str(BACKEND_DIR / "app" / "tests" / "test_v6_fts_index.py"), "-q"]
    code, output = run_command(cmd)
    stats = parse_pytest_output(output)
    return code == 0 and stats["failed"] == 0, output, stats


@register_check("v6_fixtures", "backend")
def check_v6_fixtures():
    """Verify fixtures exist and hashes match."""
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


@register_check("frontend_type_check", "frontend")
def check_frontend_type():
    """Run frontend type-check."""
    cmd = ["npm", "run", "type-check"]
    code, output = run_command(cmd, cwd=FRONTEND_DIR)
    return code == 0, output


@register_check("frontend_unit", "frontend")
def check_frontend_unit():
    """Run frontend unit tests."""
    cmd = ["npm", "run", "test", "--", "--run"]
    code, output = run_command(cmd, cwd=FRONTEND_DIR)
    return code == 0, output


@register_check("frontend_build", "frontend")
def check_frontend_build():
    """Run frontend build."""
    cmd = ["npm", "run", "build"]
    code, output = run_command(cmd, cwd=FRONTEND_DIR)
    return code == 0, output


@register_check("e2e", "e2e")
def check_e2e(external_report: Path | None = None):
    """Run or validate Playwright E2E tests."""
    if external_report:
        if external_report.exists():
            data = json.loads(external_report.read_text(encoding="utf-8"))
            stats = data.get("stats", {})
            failed = stats.get("unexpected", 0)
            skipped = sum(1 for s in data.get("suites", []) if s.get("specHash", ""))
            return failed == 0 and skipped == 0, str(external_report)
        return False, f"Report not found: {external_report}"
    cmd = ["npx", "playwright", "test", "--reporter=json"]
    code, output = run_command(cmd, cwd=FRONTEND_DIR, env={"CI": "true"})
    return code == 0, output


def main():
    parser = argparse.ArgumentParser(description="V6 Function Closure Verification")
    parser.add_argument("--artifact-root", default="artifacts", help="Artifact output root")
    parser.add_argument("--external-e2e", type=Path, default=None, help="Pre-produced E2E report")
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_root) / "verification" / "v6"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Get current commit
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
            if name == "e2e" and args.external_e2e:
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
        "version": "v6",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha,
        "total_checks": len(results),
        "passed_checks": sum(1 for r in results if r["status"] == "pass"),
        "failed_checks": sum(1 for r in results if r["status"] != "pass"),
        "all_passed": all_passed,
        "checks": results,
    }

    report_path = artifact_dir / "v6-acceptance.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nReport saved to: {report_path}")
    print(f"Total: {report['total_checks']}, Passed: {report['passed_checks']}, Failed: {report['failed_checks']}")
    
    if all_passed:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
