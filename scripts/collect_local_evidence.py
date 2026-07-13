#!/usr/bin/env python3
"""V7.4.2-00: Collect local evidence manifest.

Generates a manifest.json recording:
- base/head SHA
- Commands run (with working dir, time, exit code)
- File SHA-256 hashes

Usage:
    python scripts/collect_local_evidence.py \
        --output artifacts/v7-4-2-local/manifest.json \
        --base-sha $(git rev-parse --short HEAD~1) \
        --head-sha $(git rev-parse --short HEAD) \
        --include backend/app/tests/test_v7_4_2_evidence_framework.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_command(cmd: list[str], cwd: str) -> dict:
    """Run a command and return its result record."""
    start = datetime.now(timezone.utc)
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd,
    )
    end = datetime.now(timezone.utc)
    return {
        "command": " ".join(cmd),
        "working_dir": cwd,
        "started_at": start.isoformat(),
        "finished_at": end.isoformat(),
        "exit_code": result.returncode,
        "stdout_lines": len(result.stdout.splitlines()) if result.stdout else 0,
        "stderr_lines": len(result.stderr.splitlines()) if result.stderr else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Collect local evidence manifest")
    parser.add_argument("--output", required=True, help="Output manifest.json path")
    parser.add_argument("--base-sha", required=True, help="Base commit SHA")
    parser.add_argument("--head-sha", required=True, help="Head commit SHA")
    parser.add_argument("--include", action="append", default=[],
                        help="Files to include in manifest (repeatable)")
    parser.add_argument("--run", action="append", default=[],
                        help="Commands to run and record (repeatable)")
    args = parser.parse_args()

    project_dir = Path(__file__).resolve().parent.parent
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "version": "v7.4.2",
        "base_sha": args.base_sha,
        "head_sha": args.head_sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commands": [],
        "files": [],
    }

    # Run and record commands
    for cmd_str in args.run:
        cmd_parts = cmd_str.split()
        record = run_command(cmd_parts, str(project_dir))
        manifest["commands"].append(record)

    # Record file hashes
    for file_path_str in args.include:
        file_path = Path(file_path_str)
        if not file_path.is_absolute():
            file_path = project_dir / file_path
        if file_path.exists() and file_path.is_file():
            manifest["files"].append({
                "path": str(file_path.relative_to(project_dir)) if str(file_path).startswith(str(project_dir)) else str(file_path),
                "sha256": sha256_file(file_path),
                "size": file_path.stat().st_size,
            })

    # Always include key project files
    key_files = [
        "docs/engineering/v7-execution-state.json",
    ]
    for kf in key_files:
        fp = project_dir / kf
        if fp.exists():
            manifest["files"].append({
                "path": kf,
                "sha256": sha256_file(fp),
                "size": fp.stat().st_size,
            })

    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifest written to {output_path}")
    print(f"  Commands: {len(manifest['commands'])}")
    print(f"  Files: {len(manifest['files'])}")


if __name__ == "__main__":
    main()
