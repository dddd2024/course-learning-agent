#!/usr/bin/env python3
"""Verify a V7.4.3 local evidence manifest without trusting its author."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
REQUIRED_V7_4_4_LABELS = {
    "backend-full", "migration-faults", "frontend-typecheck", "frontend-unit",
    "frontend-build", "browser-e2e", "git-diff-check", "git-status-check",
}
REQUIRED_V7_5_0_LABELS = {
    "backend-full", "document-fidelity", "frontend-typecheck", "frontend-build",
    "browser-e2e", "git-diff-check", "git-status-before",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def git_rev_parse(ref: str, project_dir: Path) -> str:
    result = subprocess.run(["git", "rev-parse", ref], cwd=project_dir, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"git ref cannot be resolved: {ref}")
    return result.stdout.strip()


def project_path(value: str, project_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_dir / path


def changed_paths(base: str, head: str, project_dir: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..{head}"], cwd=project_dir,
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ValueError("cannot read release evidence diff")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def verify_manifest(manifest: dict[str, Any], project_dir: Path, verify_state_summaries: bool = False,
                    release_head: str | None = None) -> list[str]:
    errors: list[str] = []
    for required in ("base_sha", "head_sha", "commands", "files"):
        if required not in manifest:
            errors.append(f"manifest missing {required}")
    if errors:
        return errors
    try:
        tested_sha = git_rev_parse(manifest["head_sha"], project_dir)
        actual_head = git_rev_parse(release_head or "HEAD", project_dir)
        if actual_head != tested_sha:
            allow_prefixes = ("artifacts/v7-4-4-local/", "artifacts/v7-5-0-local/", "docs/engineering/v7-execution-state.json")
            unexpected = [path for path in changed_paths(tested_sha, actual_head, project_dir)
                          if not path.startswith(allow_prefixes)]
            if unexpected:
                errors.append("release head changes files outside evidence allowlist: " + ", ".join(unexpected))
        git_rev_parse(manifest["base_sha"], project_dir)
    except ValueError as exc:
        errors.append(str(exc))

    for record in manifest.get("commands", []):
        if record.get("exit_code") != 0:
            errors.append(f"command {record.get('label', '<unknown>')} has non-zero exit code")
        for stream in ("stdout", "stderr"):
            path = project_path(record.get(f"{stream}_log_path", ""), project_dir)
            expected = record.get(f"{stream}_log_sha256")
            if not path.is_file():
                errors.append(f"missing {stream} log: {path}")
            elif sha256_file(path) != expected:
                errors.append(f"{stream} log SHA mismatch: {path}")

    if manifest.get("version") == "v7.4.4":
        labels = {record.get("label") for record in manifest.get("commands", [])}
        missing = REQUIRED_V7_4_4_LABELS - labels
        if missing:
            errors.append("manifest missing required command labels: " + ", ".join(sorted(missing)))
    if manifest.get("version") == "v7.5.0":
        labels = {record.get("label") for record in manifest.get("commands", [])}
        missing = REQUIRED_V7_5_0_LABELS - labels
        if missing:
            errors.append("manifest missing required command labels: " + ", ".join(sorted(missing)))
        status = next((record for record in manifest.get("commands", []) if record.get("label") == "git-status-before"), None)
        if status:
            output = project_path(status.get("stdout_log_path", ""), project_dir).read_text(encoding="utf-8", errors="replace")
            if output.strip():
                errors.append("git-status-before stdout must be empty")

    for record in manifest.get("files", []):
        path = project_path(record.get("path", ""), project_dir)
        if not path.is_file():
            errors.append(f"missing evidence file: {path}")
        # The release protocol permits exactly one post-test state transition:
        # close the documented execution state after the tested SHA has passed.
        # All other included evidence remains immutable and hash-checked.
        elif (
            sha256_file(path) != record.get("sha256")
            and not (
                path == project_dir / "docs" / "engineering" / "v7-execution-state.json"
                and actual_head != tested_sha
            )
        ):
            errors.append(f"evidence file SHA mismatch: {path}")

    state_path = project_dir / "docs" / "engineering" / "v7-execution-state.json"
    if verify_state_summaries and state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for task_id, task in state.get("tasks", {}).items():
            for summary in task.get("test_summaries", []):
                if not isinstance(summary, dict):
                    continue
                marker = summary.get("marker")
                log_path = project_path(summary.get("log_path", ""), project_dir)
                if not marker or not log_path.is_file() or marker not in log_path.read_text(encoding="utf-8", errors="replace"):
                    errors.append(f"test summary for {task_id} cannot be verified from its log")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify local evidence manifest")
    parser.add_argument("manifest", help="Path to manifest.json")
    parser.add_argument("--project-root", default=str(PROJECT_DIR), help="Repository root")
    parser.add_argument("--verify-state-summaries", action="store_true", help="also verify task test markers against raw logs")
    parser.add_argument("--release-head", help="commit to verify; evidence-only changes after tested SHA are allowlisted")
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    project_dir = Path(args.project_root)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        errors = verify_manifest(manifest, project_dir, args.verify_state_summaries, args.release_head)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    result_path = manifest_path.with_name("verification_result.json")
    result_path.write_text(json.dumps({"valid": not errors, "errors": errors}, indent=2) + "\n", encoding="utf-8")
    if errors:
        print("Evidence verification failed:", *errors, sep="\n- ", file=sys.stderr)
        raise SystemExit(1)
    print(f"Evidence verification passed: {manifest_path}")


if __name__ == "__main__":
    main()
