"""Run the V4 acceptance gate without swallowing failures."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NPM = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
COMMANDS = [
    ("migration", [sys.executable, "scripts/migrate.py", "--dry-run", "--json", str(ROOT / "artifacts" / "migration-dry-run.json")], ROOT),
    ("backend", [sys.executable, "-m", "pytest", "backend/app/tests", "-q"], ROOT),
    ("frontend_type", [NPM, "run", "type-check"], ROOT / "frontend"),
    ("frontend_unit", [NPM, "run", "test", "--", "--run"], ROOT / "frontend"),
    ("frontend_build", [NPM, "run", "build"], ROOT / "frontend"),
]
def main() -> int:
    artifacts = ROOT / "artifacts" / "verification"; artifacts.mkdir(parents=True, exist_ok=True)
    results = []
    for name, command, cwd in COMMANDS:
        started = time.monotonic(); run = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
        (artifacts / f"{name}.log").write_text(run.stdout + "\n" + run.stderr, encoding="utf-8")
        results.append({"name": name, "command": command, "exit_code": run.returncode, "duration_seconds": round(time.monotonic()-started, 3), "skipped": " skipped" in (run.stdout + run.stderr).lower()})
    payload = {"version": "v4", "results": results, "passed": all(x["exit_code"] == 0 and not x["skipped"] for x in results)}
    (artifacts / "v4-baseline.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["passed"] else 1
if __name__ == "__main__": raise SystemExit(main())
