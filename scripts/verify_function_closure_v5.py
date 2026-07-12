"""Machine-readable V5 functional-closure acceptance gate.

The gate deliberately executes commands without shell pipelines.  Every check
records the command, its exit code and parsed pass/fail/skip counts so CI can
reject both real failures and a silently skipped critical regression suite.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
NPM = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
SKIP_RE = re.compile(r"(?:\b(\d+)\s+skipped\b|\bskipped\s*[:(]\s*(\d+))", re.I)
PASS_RE = re.compile(r"\b(\d+)\s+passed\b", re.I)
FAIL_RE = re.compile(r"(?:\b(\d+)\s+failed\b|\b(\d+)\s+unexpected\b)", re.I)


def _counts(output: str, exit_code: int) -> tuple[int, int, int]:
    """Return conservative passed, failed and skipped counters from runner output."""
    skipped = sum(int(a or b) for a, b in SKIP_RE.findall(output))
    passed = sum(int(value) for value in PASS_RE.findall(output))
    failed = sum(int(a or b) for a, b in FAIL_RE.findall(output))
    if exit_code and not failed:
        failed = 1
    return passed, failed, skipped


def _run(
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    log_dir: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.run(command, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, env=env)
    output = (process.stdout or "") + (process.stderr or "")
    (log_dir / f"{name}.log").write_text(output, encoding="utf-8")
    passed, failed, skipped = _counts(output, process.returncode)
    status = "pass" if process.returncode == 0 and failed == 0 and skipped == 0 else "fail"
    return {
        "check": name,
        "command": command,
        "exit_code": process.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "passed_count": passed,
        "failed_count": failed,
        "skipped_count": skipped,
        "status": status,
        "message": f"exit_code={process.returncode}, failed={failed}, skipped={skipped}",
    }


def _playwright_result(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    stats = data.get("stats", {})
    passed = int(stats.get("expected", 0))
    failed = int(stats.get("unexpected", 0))
    skipped = int(stats.get("skipped", 0))
    status = "pass" if failed == 0 and skipped == 0 and passed > 0 else "fail"
    return {
        "check": "e2e",
        "command": ["playwright", "json", str(path)],
        "exit_code": 0 if status == "pass" else 1,
        "duration_seconds": 0,
        "passed_count": passed,
        "failed_count": failed,
        "skipped_count": skipped,
        "status": status,
        "message": f"exit_code={0 if status == 'pass' else 1}, failed={failed}, skipped={skipped}",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", default=str(ROOT / "artifacts"))
    parser.add_argument("--external-e2e", help="Playwright JSON report already produced by CI")
    args = parser.parse_args()

    artifact_root = Path(args.artifact_root).resolve()
    log_dir = artifact_root / "verification" / "v5"
    log_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="v5-acceptance-") as temporary:
        temp = Path(temporary)
        backend_db = f"sqlite:///{(temp / 'backend.db').as_posix()}"
        migration_db = f"sqlite:///{(temp / 'migration.db').as_posix()}"
        e2e_db = f"sqlite:///{(temp / 'e2e.db').as_posix()}"
        base_env = os.environ.copy()
        base_env["PYTHONPATH"] = str(ROOT / "backend") + os.pathsep + base_env.get("PYTHONPATH", "")
        base_env["LLM_PROVIDER"] = "mock"

        def command_env(database_url: str | None = None) -> dict[str, str]:
            env = base_env.copy()
            if database_url:
                env["DATABASE_URL"] = database_url
            return env

        results.append(_run(
            "backend_schema",
            [sys.executable, "-c", "from app.models import Base; from app.core.database import engine; Base.metadata.create_all(engine)"],
            ROOT,
            command_env(backend_db),
            log_dir,
        ))
        results.append(_run(
            "migration",
            [sys.executable, "scripts/migrate.py", "--dry-run", "--json", str(log_dir / "migration-dry-run.json")],
            ROOT,
            command_env(migration_db),
            log_dir,
        ))
        results.append(_run(
            "backend",
            [sys.executable, "-m", "pytest", "backend/app/tests", "-q"],
            ROOT,
            command_env(backend_db),
            log_dir,
        ))

        frontend_env = command_env()
        for name, command in (
            ("frontend_type", [NPM, "run", "type-check"]),
            ("frontend_unit", [NPM, "run", "test", "--", "--run"]),
            ("frontend_build", [NPM, "run", "build"]),
        ):
            results.append(_run(name, command, ROOT / "frontend", frontend_env, log_dir))

        if args.external_e2e:
            results.append(_playwright_result(Path(args.external_e2e)))
        else:
            results.append(_run(
                "e2e_schema",
                [sys.executable, "-c", "from app.models import Base; from app.core.database import engine; Base.metadata.create_all(engine)"],
                ROOT,
                command_env(e2e_db),
                log_dir,
            ))
            e2e_env = command_env(e2e_db)
            e2e_report = log_dir / "playwright-results.json"
            e2e_env["PLAYWRIGHT_JSON_OUTPUT"] = str(e2e_report)
            run = _run("e2e", [NPM, "run", "test:e2e"], ROOT / "frontend", e2e_env, log_dir)
            if e2e_report.exists():
                parsed = _playwright_result(e2e_report)
                run.update({key: value for key, value in parsed.items() if key not in {"check", "command", "duration_seconds"}})
            results.append(run)

        # These suites are independent V5 contracts.  Keeping them as named
        # checks makes a missing regression test a failure instead of a claim.
        for name, test_file in (
            ("document_quality", "backend/app/tests/test_v5_document_parser.py"),
            ("image_integrity", "backend/app/tests/test_v5_image_integrity.py"),
            ("deletion_consistency", "backend/app/tests/test_v5_material_delete.py"),
            ("plan_closure", "backend/app/tests/test_v5_plan_state.py"),
            ("knowledge_grounding", "backend/app/tests/test_v5_knowledge_grounding.py"),
            ("multi_schedule", "backend/app/tests/test_v5_multi_schedule.py"),
            ("retrieval", "backend/app/tests/test_v5_retrieval.py"),
            ("parse_job", "backend/app/tests/test_v5_parse_jobs.py"),
        ):
            results.append(_run(
                name,
                [sys.executable, "-m", "pytest", test_file, "-q"],
                ROOT,
                command_env(backend_db),
                log_dir,
            ))

    payload = {
        "version": "v5",
        "total_checks": len(results),
        "checks": results,
        "results": results,
        "passed": all(item["status"] == "pass" for item in results),
    }
    output = artifact_root / "verification" / "v5-acceptance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
