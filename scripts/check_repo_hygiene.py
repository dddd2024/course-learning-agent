#!/usr/bin/env python3
"""Fail when generated, local-only, secret, or unexpected binary files are tracked.

The primary rule is intentionally simple: a file that matches the repository's
.gitignore must not remain in Git's index. Additional checks cover common
runtime artefacts and unknown binary blobs even when .gitignore is incomplete.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable


FORBIDDEN_COMPONENTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "dist-ssr",
    "build",
    "htmlcov",
    "playwright-report",
    "test-results",
    ".e2e-runs",
    "storage",
    "artifacts",
    "tmp",
    "logs",
    ".idea",
    ".vscode",
}

FORBIDDEN_FILENAMES = {
    ".coverage",
    ".DS_Store",
    "Thumbs.db",
    "ehthumbs.db",
    "Desktop.ini",
    "credentials.json",
    "playwright-results.json",
}

FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".dylib",
    ".o",
    ".obj",
    ".class",
    ".exe",
    ".bin",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".tmp",
    ".bak",
    ".swp",
    ".swo",
    ".zip",
    ".7z",
    ".rar",
    ".tar",
    ".gz",
    ".whl",
}

# Binary document/image fixtures and web assets may be legitimate source files.
ALLOWED_BINARY_SUFFIXES = {
    ".pdf",
    ".docx",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
}

MAX_TRACKED_FILE_BYTES = 10 * 1024 * 1024


def _run_git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def _git_paths(root: Path, *args: str) -> list[str]:
    raw = _run_git(root, *args, "-z")
    return [item.decode("utf-8", errors="surrogateescape") for item in raw.split(b"\0") if item]


def _git_index(root: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    for record in _run_git(root, "ls-files", "-s", "-z").split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        _mode, blob_sha, _stage = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8", errors="surrogateescape")
        index[path] = blob_sha
    return index


def _path_rule_reasons(path: str) -> list[str]:
    pure = PurePosixPath(path)
    reasons: list[str] = []
    forbidden = sorted(set(pure.parts) & FORBIDDEN_COMPONENTS)
    if forbidden:
        reasons.append(f"forbidden path component(s): {', '.join(forbidden)}")

    name = pure.name
    lower_name = name.lower()
    if name in FORBIDDEN_FILENAMES:
        reasons.append("forbidden generated/local filename")
    if lower_name == ".env" or (lower_name.startswith(".env.") and lower_name != ".env.example"):
        reasons.append("environment file may contain local secrets")
    if lower_name.endswith(".egg-info"):
        reasons.append("Python packaging build metadata")
    if ".db.backup-" in lower_name or lower_name.endswith((".db-journal", ".db-wal", ".db-shm")):
        reasons.append("database runtime/backup file")
    if pure.suffix.lower() in FORBIDDEN_SUFFIXES:
        reasons.append(f"forbidden generated/binary suffix: {pure.suffix.lower()}")
    return reasons


def _looks_binary(path: Path) -> bool:
    with path.open("rb") as handle:
        return b"\0" in handle.read(8192)


def _violation(path: str, blob_sha: str, reasons: list[str]) -> dict[str, object]:
    return {"path": path, "blob_sha": blob_sha, "reasons": reasons}


def audit_repository(root: Path) -> dict:
    index = _git_index(root)
    tracked = sorted(index)
    tracked_but_ignored = sorted(_git_paths(root, "ls-files", "-ci", "--exclude-standard"))
    violations: list[dict[str, object]] = []

    for path in tracked_but_ignored:
        violations.append(_violation(path, index[path], ["tracked file matches .gitignore"]))

    already_reported = set(tracked_but_ignored)
    for relative in tracked:
        full_path = root / relative
        reasons = _path_rule_reasons(relative)
        try:
            size = full_path.stat().st_size
        except OSError as exc:
            reasons.append(f"cannot stat tracked file: {exc}")
            size = -1

        if size > MAX_TRACKED_FILE_BYTES:
            reasons.append(f"tracked file exceeds {MAX_TRACKED_FILE_BYTES} bytes")

        suffix = PurePosixPath(relative).suffix.lower()
        if size >= 0 and suffix not in ALLOWED_BINARY_SUFFIXES:
            try:
                if _looks_binary(full_path):
                    reasons.append("unexpected binary content")
            except OSError as exc:
                reasons.append(f"cannot inspect tracked file: {exc}")

        if reasons and relative not in already_reported:
            violations.append(_violation(relative, index[relative], reasons))

    violations.sort(key=lambda item: str(item["path"]))
    return {
        "schema_version": 1,
        "repository_root": str(root),
        "tracked_file_count": len(tracked),
        "tracked_but_ignored_count": len(tracked_but_ignored),
        "violation_count": len(violations),
        "violations": violations,
        "status": "passed" if not violations else "failed",
    }


def _write_json(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--json-out", help="optional machine-readable report path")
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = Path(args.root).resolve()
    try:
        report = audit_repository(root)
    except RuntimeError as exc:
        print(f"REPOSITORY_HYGIENE_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json_out:
        _write_json(Path(args.json_out), report)

    print(
        "Repository hygiene: "
        f"tracked={report['tracked_file_count']} "
        f"tracked_but_ignored={report['tracked_but_ignored_count']} "
        f"violations={report['violation_count']}"
    )
    for item in report["violations"]:
        reasons = "; ".join(str(reason) for reason in item["reasons"])
        print(f"::error file={item['path']}::{reasons}")

    if report["violations"]:
        print("REPOSITORY_HYGIENE_FAILED", file=sys.stderr)
        return 1
    print("REPOSITORY_HYGIENE_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
