"""Execute the V7.5.3 local release gate on one clean committed SHA.

The script never changes execution state.  It writes machine-readable evidence
under the ignored ``artifacts/v7-5-3-local`` directory for independent review.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
ARTIFACT_ROOT = ROOT / "artifacts" / "v7-5-3-local"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_text(command: list[str], cwd: Path = ROOT, env: dict | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}")
    return completed.stdout.strip()


def git(*args: str) -> str:
    return run_text(["git", *args])


def parse_pytest_counts(output: str) -> dict:
    result = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for key in result:
        match = re.search(rf"(\d+)\s+{key}", output)
        if match:
            result[key] = int(match.group(1))
    return result


def parse_playwright_counts(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    stats = payload.get("stats", {})
    return {
        "passed": int(stats.get("expected", 0)),
        "failed": int(stats.get("unexpected", 0)),
        "flaky": int(stats.get("flaky", 0)),
        "skipped": int(stats.get("skipped", 0)),
    }


def execute_step(name: str, command: list[str], cwd: Path, run_dir: Path, env: dict | None = None) -> dict:
    started = now()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    ended = now()
    stdout_path = run_dir / f"{name}.stdout.txt"
    stderr_path = run_dir / f"{name}.stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    return {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "started_at": started,
        "ended_at": ended,
        "exit_code": completed.returncode,
        "stdout": str(stdout_path.relative_to(ROOT)).replace("\\", "/"),
        "stderr": str(stderr_path.relative_to(ROOT)).replace("\\", "/"),
        "pytest": parse_pytest_counts(completed.stdout + "\n" + completed.stderr) if "pytest" in command else None,
    }


def main() -> int:
    tested_sha = git("rev-parse", "HEAD")
    dirty_before = bool(git("status", "--porcelain"))
    if dirty_before:
        print("Release gate refused: working tree is dirty", file=sys.stderr)
        return 2

    run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
    run_dir = ARTIFACT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    playwright_json = run_dir / "playwright-results.json"

    npm = shutil.which("npm") or "npm"
    npx = shutil.which("npx") or "npx"
    env = os.environ.copy()
    env["PLAYWRIGHT_JSON_OUTPUT"] = str(playwright_json)

    metadata = {
        "python": sys.version,
        "node": run_text(["node", "--version"]),
        "npm": run_text([npm, "--version"]),
        "playwright": run_text([npx, "playwright", "--version"], cwd=FRONTEND),
    }

    steps = [
        execute_step("backend-full", [sys.executable, "-m", "pytest"], ROOT / "backend", run_dir),
        execute_step(
            "backend-v753",
            [sys.executable, "-m", "pytest", "app/tests/test_v7_5_3_*.py", "-q"],
            ROOT / "backend",
            run_dir,
        ),
        execute_step("frontend-unit", [npm, "run", "test"], FRONTEND, run_dir),
        execute_step("frontend-typecheck", [npm, "run", "type-check"], FRONTEND, run_dir),
        execute_step("frontend-build", [npm, "run", "build"], FRONTEND, run_dir),
        execute_step(
            "frontend-e2e",
            [npx, "playwright", "test", "tests/e2e/v7-5-3-user-paths.spec.ts"],
            FRONTEND,
            run_dir,
            env,
        ),
    ]

    final_sha = git("rev-parse", "HEAD")
    dirty_after = bool(git("status", "--porcelain"))
    e2e_counts = parse_playwright_counts(playwright_json) if playwright_json.exists() else {
        "passed": 0, "failed": 1, "flaky": 0, "skipped": 0,
    }

    teardown_files = sorted((FRONTEND / "test-results" / "e2e-runtime").glob("*/teardown-result.json"))
    teardown = json.loads(teardown_files[-1].read_text(encoding="utf-8")) if teardown_files else {
        "passed": False,
        "normal_uploads_unchanged": False,
        "cleanup_passed": False,
    }

    passed = (
        all(step["exit_code"] == 0 for step in steps)
        and tested_sha == final_sha
        and not dirty_before
        and not dirty_after
        and e2e_counts["passed"] == 6
        and e2e_counts["failed"] == 0
        and bool(teardown.get("passed"))
        and bool(teardown.get("normal_uploads_unchanged"))
    )

    result = {
        "schema_version": 1,
        "run_id": run_id,
        "tested_sha": tested_sha,
        "final_sha": final_sha,
        "head_unchanged": tested_sha == final_sha,
        "dirty_before": dirty_before,
        "dirty_after": dirty_after,
        "metadata": metadata,
        "steps": steps,
        "e2e": e2e_counts,
        "teardown": teardown,
        "normal_uploads_unchanged": bool(teardown.get("normal_uploads_unchanged")),
        "passed": passed,
        "started_at": steps[0]["started_at"],
        "completed_at": now(),
    }
    result_path = run_dir / "release-gate-result.json"
    encoded = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
    result_path.write_bytes(encoded)
    (run_dir / "release-gate-result.sha256").write_text(hashlib.sha256(encoded).hexdigest() + "\n", encoding="ascii")

    print(result_path)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
