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
        # The backend suite includes isolated parse-worker and document
        # fixtures; allow it to finish instead of converting a healthy
        # full-suite result into a false acceptance failure.
        timeout=600,
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


@register_check("legacy_page_catalog_contract", "backend")
def check_legacy_page_catalog_contract():
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v7_5_2_legacy_page_catalog.py"))


@register_check("existing_db_autoincrement_migration", "backend")
def check_existing_db_autoincrement_migration():
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v7_5_2_legacy_database_migration.py"))


@register_check("material_public_identity", "backend")
def check_material_public_identity():
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v7_5_2_material_public_identity.py"))


@register_check("page_backfill_failure_contract", "backend")
def check_page_backfill_failure_contract():
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_v7_5_2_page_backfill_failure.py"))


@register_check("document_reader_four_fixes", "backend")
def check_document_reader_four_fixes():
    """Capability split, idempotent FTS, geometry, and selection evidence."""
    return _run_pytest(str(BACKEND_DIR / "app" / "tests" / "test_document_reader_four_fixes.py"))


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
AUDIT_E2E_IDS = ["P0-L01", "P0-L02B", "P0-L02C", "P1-L03", "P2-L04", "P1-ID01", "P1-ID02", "P1-ID03"]


def _playwright_statuses(data: dict) -> tuple[dict[str, list[str]], int, int]:
    """Return concrete final statuses for each reported Playwright title."""
    statuses: dict[str, list[str]] = {}

    def visit(node: dict) -> None:
        title = node.get("title", "")
        tests = node.get("tests", [])
        if title and tests:
            final = []
            for test in tests:
                results = test.get("results", [])
                final.extend(result.get("status", "unknown") for result in results[-1:])
            statuses.setdefault(title, []).extend(final or ["unknown"])
        for child in node.get("specs", []):
            visit(child)
        for child in node.get("suites", []):
            visit(child)

    for suite in data.get("suites", []):
        visit(suite)
    for spec in data.get("specs", []):
        visit(spec)
    stats = data.get("stats", {})
    return statuses, int(stats.get("unexpected", 0)), int(stats.get("skipped", 0))


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

    statuses, failed, skipped = _playwright_statuses(data)

    # Check each V7-E2E scenario
    missing = []
    for eid in V7_E2E_IDS:
        matching = [state for title, state in statuses.items() if eid in title]
        if not matching or any(status != "passed" for state in matching for status in state):
            missing.append(eid)
    for eid in AUDIT_E2E_IDS:
        matching = [state for title, state in statuses.items() if eid in title]
        if not matching or any(status != "passed" for state in matching for status in state):
            missing.append(eid)

    if missing:
        return False, f"Missing V7 E2E scenarios: {', '.join(missing)}"

    # Check overall stats
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


def _remote_ci_state(artifact_dir: Path, commit_sha: str) -> dict:
    """Remote evidence is optional for local acceptance, never for release."""
    path = artifact_dir / "remote-ci.json"
    unavailable = {
        "commit_sha": commit_sha,
        "status": "unavailable",
        "reason": "remote_ci_evidence_not_collected",
    }
    if not path.exists():
        return unavailable
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {**unavailable, "reason": "remote_ci_evidence_invalid"}
    if evidence.get("commit_sha") != commit_sha:
        return {**unavailable, "reason": "remote_ci_commit_mismatch"}
    return evidence


def main():
    parser = argparse.ArgumentParser(description="V7 Function Closure Verification")
    parser.add_argument("--artifact-root", default="artifacts", help="Artifact output root")
    parser.add_argument("--external-e2e", type=Path, default=None, help="Pre-produced E2E report")
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_root) / "verification" / "v7-audit-recovery"
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
        "v7_e2e_scenarios": V7_E2E_IDS + AUDIT_E2E_IDS,
        "checks": results,
    }

    report_path = artifact_dir / "v7-acceptance.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    playwright_report = args.external_e2e or (FRONTEND_DIR / "playwright-results.json")
    playwright_failed = playwright_skipped = 0
    if playwright_report.exists():
        playwright_data = json.loads(playwright_report.read_text(encoding="utf-8"))
        _, playwright_failed, playwright_skipped = _playwright_statuses(playwright_data)
    remote_ci = _remote_ci_state(artifact_dir, commit_sha)
    by_name = {entry["name"]: entry["status"] for entry in results}
    playwright_statuses = _playwright_statuses(playwright_data)[0] if playwright_report.exists() else {}
    def e2e_passed(eid: str) -> bool:
        return any(eid in title and all(value == "passed" for value in values) for title, values in playwright_statuses.items())
    summary = {
        "commit_sha": commit_sha,
        "acceptance": "passed" if all_passed else "failed",
        "total_checks": len(results),
        "failed_checks": report["failed_checks"],
        "playwright_failed": playwright_failed,
        "playwright_skipped": playwright_skipped,
        "legacy_migration": "passed" if by_name.get("existing_db_autoincrement_migration") == "pass" else "failed",
        "page_backfill_failure_contract": "pass" if by_name.get("page_backfill_failure_contract") == "pass" else "fail",
        "image_reextract_partial_success": "pass" if e2e_passed("P0-L02C") else "fail",
        "public_id_schema_constraints": "pass" if by_name.get("existing_db_autoincrement_migration") == "pass" else "fail",
        "public_id_learning_links": "pass" if all(e2e_passed(eid) for eid in ["P1-ID01", "P1-ID02", "P1-ID03"]) else "fail",
        "remote_ci": remote_ci.get("status", "unavailable"),
        "release_ready": all_passed and remote_ci.get("status") == "success",
        "generated_at": report["timestamp"],
    }
    (artifact_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "commit.txt").write_text(f"{commit_sha}\n", encoding="utf-8")
    (artifact_dir / "playwright-summary.json").write_text(json.dumps({
        "report": str(playwright_report), "failed": playwright_failed, "skipped": playwright_skipped,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

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
