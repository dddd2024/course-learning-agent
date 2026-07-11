"""Run the V4 acceptance gate without swallowing failures."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NPM = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
def main() -> int:
    artifacts = ROOT / "artifacts" / "verification"; artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v4-acceptance-") as temporary:
        temp = Path(temporary)
        backend_url = f"sqlite:///{(temp / 'backend.db').as_posix()}"
        commands = [
            ("backend_schema", [sys.executable, "-c", "from app.models import Base; from app.core.database import engine; Base.metadata.create_all(engine)"], ROOT, backend_url),
            ("migration", [sys.executable, "scripts/migrate.py", "--dry-run", "--json", str(artifacts / "migration-dry-run.json")], ROOT, f"sqlite:///{(temp / 'migration.db').as_posix()}"),
            ("backend", [sys.executable, "-c", "from app.models import Base; from app.core.database import engine; Base.metadata.create_all(engine); import pytest; raise SystemExit(pytest.main(['backend/app/tests', '-q']))"], ROOT, backend_url),
            ("frontend_type", [NPM, "run", "type-check"], ROOT / "frontend", None),
            ("frontend_unit", [NPM, "run", "test", "--", "--run"], ROOT / "frontend", None),
            ("frontend_build", [NPM, "run", "build"], ROOT / "frontend", None),
        ]
        results = []
        for name, command, cwd, database_url in commands:
            env = os.environ.copy()
            if database_url:
                env["DATABASE_URL"] = database_url
                env["PYTHONPATH"] = str(ROOT / "backend") + os.pathsep + env.get("PYTHONPATH", "")
            started = time.monotonic(); run = subprocess.run(command, cwd=cwd, text=True, capture_output=True, env=env)
            output = run.stdout + "\n" + run.stderr
            skipped = " skipped" in output.lower()
            (artifacts / f"{name}.log").write_text(output, encoding="utf-8")
            results.append({"name": name, "command": command, "exit_code": run.returncode, "duration_seconds": round(time.monotonic()-started, 3), "skipped": skipped})
    checks = [{"check": item["name"], "status": "pass" if item["exit_code"] == 0 and not item["skipped"] else "fail", "message": f"exit_code={item['exit_code']}, skipped={str(item['skipped']).lower()}"} for item in results]
    payload = {"version": "v4", "total_checks": len(checks), "checks": checks, "results": results, "passed": all(item["status"] == "pass" for item in checks)}
    (artifacts / "v4-baseline.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["passed"] else 1
if __name__ == "__main__": raise SystemExit(main())
