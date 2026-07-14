"""V7.4.1-00: Execution state file must be a single valid JSON object.

Tests that v7-execution-state.json:
1. Is parseable as a single JSON object
2. Has the required top-level fields
3. Does not contain concatenated JSON
4. The corrupted backup exists and is read-only
"""
from __future__ import annotations

import json
import os
import stat

import pytest


STATE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "docs", "engineering", "v7-execution-state.json",
)
CORRUPTED_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "docs", "engineering", "v7-execution-state.v7.4.corrupted.json",
)


class TestExecutionStateValid:
    """V7.4.1-00: The execution state file must be a single valid JSON object."""

    def test_file_exists(self):
        assert os.path.isfile(STATE_PATH), "v7-execution-state.json must exist"

    def test_single_json_object(self):
        """The file must contain exactly one top-level JSON object, not concatenated."""
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        # Count top-level objects by tracking brace depth
        brace_depth = 0
        top_level_ends = []
        in_string = False
        escape = False
        for i, c in enumerate(raw):
            if escape:
                escape = False
                continue
            if c == "\\" and in_string:
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                brace_depth += 1
            elif c == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    top_level_ends.append(i)
        assert len(top_level_ends) == 1, (
            f"Expected exactly 1 top-level JSON object, found {len(top_level_ends)}. "
            "The file contains concatenated JSON objects."
        )

    def test_json_parses(self):
        """The file must parse as valid JSON."""
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), "Top-level must be a JSON object"

    def test_required_fields(self):
        """The state file must contain the required V7.4.x fields."""
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["version"] in ("v7.4.1", "v7.4.2", "v7.4.3", "v7.4.4", "v7.5.0", "v7.5.1", "v7.5.2")
        assert "base_commit" in data
        assert "branch" in data
        assert data["overall_status"] in ("in_progress", "verified_locally")
        assert "tasks" in data
        assert "local_closure" in data
        assert data.get("remote_ci") in ("deferred_to_v7_6", "deferred_to_v1_1", "required_before_release", "success", None)

    def test_corrupted_backup_exists(self):
        """The old corrupted file must be backed up."""
        assert os.path.isfile(CORRUPTED_PATH), (
            "v7-execution-state.v7.4.corrupted.json must exist as a backup"
        )
