#!/usr/bin/env python3
"""Collect reproducible, tamper-evident local verification evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relative_path(path: Path, project_dir: Path) -> str:
    try:
        return path.relative_to(project_dir).as_posix()
    except ValueError:
        return str(path)


def normalise_command(command: list[str] | str) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command, posix=False)
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise ValueError("command must be a non-empty string or array of strings")
    return command


def run_command(command: list[str] | str, cwd: Path, logs_dir: Path, label: str, project_dir: Path) -> dict[str, Any]:
    args = normalise_command(command)
    started_at = utc_now()
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        check=False,
    )
    finished_at = utc_now()
    safe_label = "".join(char if char.isalnum() or char in "-_" else "_" for char in label)
    stdout_path = logs_dir / f"{safe_label}.stdout.log"
    stderr_path = logs_dir / f"{safe_label}.stderr.log"
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    return {
        "label": label,
        "command": args,
        "working_dir": relative_path(cwd, project_dir),
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": result.returncode,
        "stdout_log_path": relative_path(stdout_path, project_dir),
        "stdout_log_sha256": sha256_file(stdout_path),
        "stderr_log_path": relative_path(stderr_path, project_dir),
        "stderr_log_sha256": sha256_file(stderr_path),
    }


def resolve_path(value: str, project_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_dir / path


def load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("evidence config must be an object")
    return data


def resolve_git_ref(value: str) -> str:
    if value not in {"HEAD", "BASE"}:
        return value
    result = subprocess.run(["git", "rev-parse", value], cwd=PROJECT_DIR, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"cannot resolve git ref: {value}")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect local evidence manifest")
    parser.add_argument("--config", help="JSON run plan containing command arrays and included files")
    parser.add_argument("--output", help="Output manifest.json path (legacy/direct mode)")
    parser.add_argument("--base-sha", help="Base commit SHA (legacy/direct mode)")
    parser.add_argument("--head-sha", help="Head commit SHA (legacy/direct mode)")
    parser.add_argument("--include", action="append", default=[], help="File to hash (repeatable)")
    parser.add_argument("--run", action="append", default=[], help="Command to run (repeatable; parsed with shlex)")
    args = parser.parse_args()

    config: dict[str, Any] = {}
    config_path: Path | None = None
    if args.config:
        config_path = resolve_path(args.config, PROJECT_DIR)
        config = load_config(config_path)

    output_value = args.output or config.get("output")
    if not output_value:
        output_value = str(config_path.parent / "manifest.json") if config_path else None
    if not output_value:
        parser.error("--output is required when --config is not supplied")
    output_path = resolve_path(output_value, PROJECT_DIR)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logs_dir = output_path.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    base_sha = args.base_sha or config.get("base_sha")
    head_sha = args.head_sha or config.get("head_sha")
    if not base_sha or not head_sha:
        parser.error("base_sha and head_sha are required")
    base_sha = resolve_git_ref(base_sha)
    head_sha = resolve_git_ref(head_sha)

    command_specs = config.get("commands", [])
    if args.run:
        command_specs += [{"label": f"command-{index + 1}", "command": command} for index, command in enumerate(args.run)]
    includes = list(config.get("include", [])) + args.include
    manifest: dict[str, Any] = {
        "version": config.get("version", "v7.4.3"),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "generated_at": utc_now(),
        "commands": [],
        "files": [],
    }

    for index, spec in enumerate(command_specs):
        if not isinstance(spec, dict) or "command" not in spec:
            raise ValueError("each command must be an object with a command field")
        cwd = resolve_path(spec.get("cwd", "."), PROJECT_DIR)
        if not cwd.is_dir():
            raise ValueError(f"command working directory does not exist: {cwd}")
        manifest["commands"].append(run_command(spec["command"], cwd, logs_dir, spec.get("label", f"command-{index + 1}"), PROJECT_DIR))

    include_values = ["docs/engineering/v7-execution-state.json", *includes]
    seen: set[str] = set()
    for value in include_values:
        file_path = resolve_path(value, PROJECT_DIR)
        key = str(file_path.resolve())
        if key in seen:
            continue
        seen.add(key)
        if not file_path.is_file():
            raise FileNotFoundError(f"declared evidence file does not exist: {file_path}")
        manifest["files"].append({"path": relative_path(file_path, PROJECT_DIR), "sha256": sha256_file(file_path), "size": file_path.stat().st_size})

    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Manifest written to {output_path}")
    print(f"Commands: {len(manifest['commands'])}; files: {len(manifest['files'])}")


if __name__ == "__main__":
    main()
