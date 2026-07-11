#!/usr/bin/env python3
"""V3 Quality Closure Verification Script.

Verifies that the V3 quality-closure baseline is met by checking:

1. No hardcoded quiz content ("梯度下降") in backend/app/agents/
2. No direct status="success" in AgentAudit.finish_run calls (agents must
   use the _safe_finish_run / finalize_run wrapper pattern)
3. V3 test files exist and pass via pytest
4. Citation support_status allows "verified"/"supported" for formal
   citations (not just "weak")
5. Quiz items carry source_evidence linked to chunks with quote_text

Outputs a JSON report to stdout and exits 0 (all pass) or 1 (any fail).

Usage:
    python scripts/verify_quality_closure_v3.py [--json]
    python scripts/verify_quality_closure_v3.py --check no_hardcoded_quiz
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
AGENTS_DIR = BACKEND_DIR / "app" / "agents"
TESTS_DIR = BACKEND_DIR / "app" / "tests"
BACKEND_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"

# V3 closure test files — these are the tests that validate the v3
# concept-graph closure work (evidence hashing, legacy DB migration,
# user_focus enum, compare behavior).
V3_TEST_FILES = [
    "test_concept_compare_agent.py",
    "test_concept_graph_api.py",
    "test_db_migrations.py",
]

# Key V3 behavior test node-ids that must pass.
V3_KEY_TEST_IDS = [
    "app/tests/test_concept_compare_agent.py::test_compare_cache_invalidates_when_evidence_text_changes",
    "app/tests/test_concept_compare_agent.py::test_compare_rejects_mismatched_edge_id",
    "app/tests/test_concept_graph_api.py::test_compare_invalid_user_focus_returns_422",
    "app/tests/test_concept_graph_api.py::test_compare_mismatched_edge_returns_400",
]


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _ok(check_id: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "check": check_id,
        "status": "pass",
        "message": message,
        "details": details or {},
    }


def _fail(check_id: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "check": check_id,
        "status": "fail",
        "message": message,
        "details": details or {},
    }


# ---------------------------------------------------------------------------
# Check 1: No hardcoded quiz content ("梯度下降") in agents
# ---------------------------------------------------------------------------

def check_no_hardcoded_quiz() -> dict[str, Any]:
    """Ensure no hardcoded "梯度下降" quiz content exists in agent source.

    The mock quiz builder previously returned a fixed question about
    "梯度下降" (gradient descent) regardless of the actual course
    material. V3 requires mock builders to derive content from the
    prompt (evidence chunks), so the literal string must not appear
    in agent source code.

    We read each .py file and search for the string, excluding lines
    that are pure docstring/comment references explaining *why* the
    hardcode was removed.
    """
    check_id = "no_hardcoded_quiz"
    violations: list[dict[str, Any]] = []

    agent_files = sorted(AGENTS_DIR.glob("*.py"))
    for fpath in agent_files:
        try:
            content = fpath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append({
                "file": str(fpath.relative_to(REPO_ROOT)),
                "error": f"cannot read file: {exc}",
            })
            continue

        for lineno, line in enumerate(content.splitlines(), start=1):
            if "梯度下降" not in line:
                continue
            stripped = line.strip()
            # Skip lines that are docstring/comment *descriptions* of the
            # hardcode removal — these mention the string but do not
            # constitute hardcoded quiz content.
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Skip lines inside docstrings (multi-line) that reference the
            # term descriptively — detected by the pattern 'hardcoded'
            # or 'instead of' on the same or nearby context.
            if "hardcoded" in line.lower() or "instead of" in line.lower():
                continue
            # A string literal containing "梯度下降" in a mock builder
            # is the violation we are looking for.
            if "梯度下降" in line and ('"' in line or "'" in line):
                violations.append({
                    "file": str(fpath.relative_to(REPO_ROOT)),
                    "line": lineno,
                    "snippet": stripped[:120],
                })

    if violations:
        return _fail(
            check_id,
            f"Found {len(violations)} hardcoded '梯度下降' reference(s) in agent code",
            {"violations": violations},
        )
    return _ok(check_id, "No hardcoded '梯度下降' quiz content in agents")


# ---------------------------------------------------------------------------
# Check 2: No direct status="success" in AgentAudit.finish_run calls
# ---------------------------------------------------------------------------

def check_no_direct_success_finish() -> dict[str, Any]:
    """Ensure agents do not call AgentAudit.finish_run(status="success")
    directly.

    Direct finish_run calls bypass the _safe_finish_run / finalize_run
    wrapper that swallows audit errors. If the audit DB write fails,
    a direct call will raise and break the main agent flow. Agents
    must route through the safe wrapper instead.

    We look for ``AgentAudit.finish_run`` or ``finish_run`` calls that
    include ``status="success"`` (or ``status='success'``) on the same
    call expression, in files under backend/app/agents/.

    Calls made *inside* the _safe_finish_run wrapper definition are
    exempt — that is the one place the direct call is expected.
    """
    check_id = "no_direct_success_finish"
    violations: list[dict[str, Any]] = []

    # Match AgentAudit.finish_run( ... status="success" ... ) or
    # bare finish_run( ... status="success" ... ) that are NOT calls
    # to _safe_finish_run (the wrapper) and NOT the internal call
    # inside _safe_finish_run's definition.
    #
    # The negative lookbehind (?<!_safe_) prevents matching
    # _safe_finish_run( which is the correct wrapper call.
    direct_pattern = re.compile(
        r'(?<!_safe_)(?:AgentAudit\.)?finish_run\s*\(',
    )
    success_pattern = re.compile(
        r'status\s*=\s*["\']success["\']',
    )

    agent_files = sorted(AGENTS_DIR.glob("*.py"))
    for fpath in agent_files:
        try:
            content = fpath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append({
                "file": str(fpath.relative_to(REPO_ROOT)),
                "error": f"cannot read file: {exc}",
            })
            continue

        lines = content.splitlines()
        for i, line in enumerate(lines):
            if not direct_pattern.search(line):
                continue
            # Gather the next few lines to capture multi-line calls.
            window = "\n".join(lines[i : i + 6])
            if not success_pattern.search(window):
                continue
            # Skip the call inside _safe_finish_run definition — that is
            # the wrapper itself and is the correct pattern.
            # Look backwards for the enclosing function definition.
            func_context = "\n".join(lines[max(0, i - 15) : i])
            if re.search(r'def\s+_safe_finish_run', func_context):
                continue
            violations.append({
                "file": str(fpath.relative_to(REPO_ROOT)),
                "line": i + 1,
                "snippet": line.strip()[:120],
            })

    if violations:
        return _fail(
            check_id,
            f"Found {len(violations)} direct finish_run(status='success') call(s) "
            "— agents must use _safe_finish_run / finalize_run wrapper",
            {"violations": violations},
        )
    return _ok(
        check_id,
        "No direct finish_run(status='success') calls in agents (wrapper pattern used)",
    )


# ---------------------------------------------------------------------------
# Check 3: V3 test files exist and pass
# ---------------------------------------------------------------------------

def _run_pytest(args: list[str]) -> tuple[int, str, str]:
    """Run pytest using the backend venv Python.

    Returns (returncode, stdout, stderr).
    """
    python_exe = str(BACKEND_PYTHON)
    if not BACKEND_PYTHON.exists():
        python_exe = sys.executable
    cmd = [python_exe, "-m", "pytest"] + args
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    proc = subprocess.run(
        cmd,
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    return proc.returncode, proc.stdout, proc.stderr


def check_v3_tests_exist() -> dict[str, Any]:
    """Verify V3 test files exist on disk."""
    check_id = "v3_tests_exist"
    missing: list[str] = []
    found: list[str] = []

    for name in V3_TEST_FILES:
        fpath = TESTS_DIR / name
        if fpath.exists():
            found.append(name)
        else:
            missing.append(name)

    # Also check for test_v3_*.py pattern files.
    v3_pattern_files = sorted(TESTS_DIR.glob("test_v3_*.py"))
    for f in v3_pattern_files:
        found.append(f.name)

    if missing:
        return _fail(
            check_id,
            f"Missing {len(missing)} V3 test file(s): {', '.join(missing)}",
            {"missing": missing, "found": found},
        )
    return _ok(
        check_id,
        f"All {len(V3_TEST_FILES)} V3 test file(s) present",
        {"found": found},
    )


def check_v3_tests_pass() -> dict[str, Any]:
    """Run V3 test files via pytest and verify they pass."""
    check_id = "v3_tests_pass"
    test_args = [f"app/tests/{name}" for name in V3_TEST_FILES]
    rc, stdout, stderr = _run_pytest(test_args + ["-q", "--tb=short"])

    # Extract the summary line from pytest output.
    summary_lines = [
        line for line in stdout.splitlines()
        if "passed" in line or "failed" in line or "error" in line
    ]
    summary = summary_lines[-1].strip() if summary_lines else "(no summary)"

    if rc != 0:
        return _fail(
            check_id,
            f"V3 tests failed (exit {rc}): {summary}",
            {
                "exit_code": rc,
                "summary": summary,
                "stdout_tail": stdout[-500:] if stdout else "",
                "stderr_tail": stderr[-500:] if stderr else "",
            },
        )
    return _ok(check_id, f"V3 tests passed: {summary}", {"summary": summary})


def check_v3_key_tests_pass() -> dict[str, Any]:
    """Run the key V3 behavior test node-ids explicitly."""
    check_id = "v3_key_tests_pass"
    if not V3_KEY_TEST_IDS:
        return _ok(check_id, "No key test IDs configured (skipped)")

    rc, stdout, stderr = _run_pytest(V3_KEY_TEST_IDS + ["-q", "--tb=short"])
    summary_lines = [
        line for line in stdout.splitlines()
        if "passed" in line or "failed" in line or "error" in line
    ]
    summary = summary_lines[-1].strip() if summary_lines else "(no summary)"

    if rc != 0:
        return _fail(
            check_id,
            f"Key V3 tests failed (exit {rc}): {summary}",
            {
                "exit_code": rc,
                "summary": summary,
                "stdout_tail": stdout[-500:] if stdout else "",
                "stderr_tail": stderr[-500:] if stderr else "",
            },
        )
    return _ok(check_id, f"Key V3 tests passed: {summary}", {"summary": summary})


# ---------------------------------------------------------------------------
# Check 4: Citation support_status allows "verified"/"supported"
# ---------------------------------------------------------------------------

def check_citation_support_status() -> dict[str, Any]:
    """Verify citation support_status supports non-"weak" values.

    The Citation model and schema must:
    - Have a support_status field (not hardcode "weak" as the only value)
    - The course_qa agent must set support_status to "verified" for
      citations that pass the support check (not just "weak")

    A formal citation (one with quote_text + claim_text) must be able
    to receive "verified" status — it must not be locked to "weak".
    """
    check_id = "citation_support_status"
    details: dict[str, Any] = {}

    # 4a. Citation model has support_status field
    citation_model_path = BACKEND_DIR / "app" / "models" / "citation.py"
    try:
        model_content = citation_model_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(check_id, f"Cannot read citation model: {exc}")
    if "support_status" not in model_content:
        return _fail(check_id, "Citation model missing support_status field")
    details["model_has_support_status"] = True

    # 4b. Citation schema allows non-weak default
    citation_schema_path = BACKEND_DIR / "app" / "schemas" / "citation.py"
    try:
        schema_content = citation_schema_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(check_id, f"Cannot read citation schema: {exc}")
    if "support_status" not in schema_content:
        return _fail(check_id, "Citation schema missing support_status field")
    details["schema_has_support_status"] = True

    # 4c. course_qa agent sets support_status to "verified" (not just "weak")
    qa_agent_path = AGENTS_DIR / "course_qa.py"
    try:
        qa_content = qa_agent_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(check_id, f"Cannot read course_qa agent: {exc}")

    has_verified = '"verified"' in qa_content or "'verified'" in qa_content
    has_weak = '"weak"' in qa_content or "'weak'" in qa_content
    details["qa_agent_sets_verified"] = has_verified
    details["qa_agent_sets_weak"] = has_weak

    if not has_verified:
        return _fail(
            check_id,
            "course_qa agent never sets support_status to 'verified' — "
            "formal citations cannot be promoted beyond 'weak'",
            details,
        )

    # 4d. Verify "supported" or "verified" is used as a promotion, not just a comparison
    # Look for assignment pattern: support_status = "supported" or "verified"
    verified_assign = re.search(
        r'support_status["\']?\s*\]?\s*=\s*["\'](?:supported|verified)["\']',
        qa_content,
    )
    details["qa_agent_assigns_verified"] = bool(verified_assign)
    if not verified_assign:
        return _fail(
            check_id,
            "course_qa agent never assigns 'supported' or 'verified' "
            "to support_status — formal citations stay 'weak'",
            details,
        )

    return _ok(
        check_id,
        "Citation support_status supports 'supported'/'verified' for formal citations",
        details,
    )


# ---------------------------------------------------------------------------
# Check 5: Quiz items have source_evidence with quote_text
# ---------------------------------------------------------------------------

def check_quiz_source_evidence() -> dict[str, Any]:
    """Verify quiz items carry source evidence linked to chunks with text.

    The QuizItem model must have a source_evidence_ids field, and the
    quiz agent must:
    - Validate evidence IDs against actual MaterialChunk rows
    - Skip items without valid evidence (no orphan questions)
    - Include chunk text (quote_text) in the evidence passed to the LLM
    """
    check_id = "quiz_source_evidence"
    details: dict[str, Any] = {}

    # 5a. QuizItem model has source_evidence_ids field
    quiz_model_path = BACKEND_DIR / "app" / "models" / "quiz.py"
    try:
        quiz_model_content = quiz_model_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(check_id, f"Cannot read quiz model: {exc}")

    if "source_evidence_ids" not in quiz_model_content:
        return _fail(check_id, "QuizItem model missing source_evidence_ids field")
    details["model_has_source_evidence_ids"] = True

    if "evidence_snapshot" not in quiz_model_content:
        return _fail(check_id, "QuizItem model missing evidence_snapshot field")
    details["model_has_evidence_snapshot"] = True

    # 5b. Quiz agent validates evidence and skips orphan items
    quiz_agent_path = AGENTS_DIR / "quiz.py"
    try:
        quiz_agent_content = quiz_agent_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(check_id, f"Cannot read quiz agent: {exc}")

    has_evidence_validation = "_valid_evidence_ids" in quiz_agent_content
    details["agent_has_evidence_validation"] = has_evidence_validation
    if not has_evidence_validation:
        return _fail(
            check_id,
            "Quiz agent missing _valid_evidence_ids — no evidence validation",
        )

    # Check that items without evidence are skipped
    skip_pattern = re.search(
        r"if\s+not\s+evidence_ids\s*:.*?(?:continue|skip)",
        quiz_agent_content,
        re.DOTALL,
    )
    details["agent_skips_no_evidence"] = bool(skip_pattern)
    if not skip_pattern:
        return _fail(
            check_id,
            "Quiz agent does not skip items without valid evidence — "
            "orphan questions may be persisted",
        )

    # 5c. Quiz agent includes chunk text (quote_text) in evidence formatting
    has_format_evidence = "_format_evidence" in quiz_agent_content
    details["agent_has_format_evidence"] = has_format_evidence
    if not has_format_evidence:
        return _fail(
            check_id,
            "Quiz agent missing _format_evidence — evidence text not "
            "passed to the LLM prompt",
        )

    # Verify _format_evidence includes actual chunk text (not just IDs)
    format_evidence_func = re.search(
        r"def\s+_format_evidence\(.*?\).*?(?=\n\ndef\s|\Z)",
        quiz_agent_content,
        re.DOTALL,
    )
    if format_evidence_func:
        func_body = format_evidence_func.group(0)
        has_text_in_evidence = "r.text" in func_body or ".text" in func_body
        details["evidence_includes_text"] = has_text_in_evidence
        if not has_text_in_evidence:
            return _fail(
                check_id,
                "_format_evidence does not include chunk text — "
                "evidence lacks quote_text content",
            )
    else:
        details["evidence_includes_text"] = "unknown (function not found)"

    # 5d. Quiz items dict includes source_evidence_ids
    items_have_evidence = "source_evidence_ids" in quiz_agent_content
    details["items_include_source_evidence_ids"] = items_have_evidence
    if not items_have_evidence:
        return _fail(
            check_id,
            "Quiz agent does not populate source_evidence_ids on items",
        )

    return _ok(
        check_id,
        "Quiz items carry source_evidence linked to chunks with quote_text",
        details,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_no_hardcoded_quiz,
    check_no_direct_success_finish,
    check_v3_tests_exist,
    check_v3_tests_pass,
    check_v3_key_tests_pass,
    check_citation_support_status,
    check_quiz_source_evidence,
]


def run_all() -> list[dict[str, Any]]:
    """Run every check and return the list of results."""
    results: list[dict[str, Any]] = []
    for check_fn in ALL_CHECKS:
        try:
            result = check_fn()
        except Exception as exc:  # noqa: BLE001 — a check crashing must not abort the rest
            result = _fail(
                check_fn.__name__,
                f"Check raised an exception: {exc}",
            )
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="V3 Quality Closure Verification Script"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON only (no per-check console output)",
    )
    parser.add_argument(
        "--check",
        type=str,
        default=None,
        help="Run a single check by function name (e.g. no_hardcoded_quiz)",
    )
    args = parser.parse_args()

    if args.check:
        check_map = {fn.__name__: fn for fn in ALL_CHECKS}
        # Also allow matching by the check_id used inside results.
        for fn in ALL_CHECKS:
            try:
                result = fn()
                check_map[result["check"]] = fn
            except Exception:
                pass
        if args.check not in check_map:
            print(f"Unknown check: {args.check}", file=sys.stderr)
            print(f"Available: {', '.join(sorted(check_map.keys()))}", file=sys.stderr)
            return 2
        try:
            result = check_map[args.check]()
        except Exception as exc:  # noqa: BLE001
            result = _fail(args.check, f"Check raised an exception: {exc}")
        results = [result]
    else:
        results = run_all()

    # Console output (unless --json suppresses it)
    if not args.json:
        for r in results:
            status_label = "PASS" if r["status"] == "pass" else "FAIL"
            print(f"[{status_label}] {r['check']}: {r['message']}")
            if r["details"]:
                for key, value in r["details"].items():
                    if isinstance(value, (list, dict)):
                        print(f"         {key}: {json.dumps(value, ensure_ascii=False)[:200]}")
                    else:
                        print(f"         {key}: {value}")
        print()

    # JSON output
    summary = {
        "task": "BASE-V3-01",
        "total_checks": len(results),
        "passed": sum(1 for r in results if r["status"] == "pass"),
        "failed": sum(1 for r in results if r["status"] == "fail"),
        "checks": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # Exit 0 if all pass, 1 if any fail
    all_pass = all(r["status"] == "pass" for r in results)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
