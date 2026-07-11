"""V3 Migration tests (BASE-V3-02).

These tests capture audit blockers in the migration script where:

- ``migrate.py --dry-run`` outputs fixed placeholder text instead of
  real statistics about what would be migrated.
- Migrations do not create a ``version`` column (or set ``version=1``)
  for historical materials, so there is no way to distinguish pre-V3
  data from post-V3 data.
- The second migration run does not explicitly report ``changed=0``
  (idempotency), making it impossible to tell whether anything was
  actually modified on subsequent runs.

Written to FAIL on the current codebase.
"""
import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from starlette.testclient import TestClient

from app.core.database import engine
from app.main import app
from app.tests.conftest import auth_headers, setup_course_with_material

TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
).encode("utf-8")

_MIGRATE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "migrate.py"
)


def _load_migrate_module():
    """Import the standalone scripts/migrate.py module."""
    spec = importlib.util.spec_from_file_location("migrate_script", _MIGRATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_outputs_real_statistics(capsys, monkeypatch, tmp_path) -> None:
    """migrate.py --dry-run should output real statistics, not fixed text.

    The current --dry-run prints only:
        dry-run: database=...
        would add compatibility columns and normalise historical task types

    The V3 fix should print actual counts (e.g. ``materials_to_migrate=N``,
    ``chunks_to_normalise=M``) so the operator knows what will change.
    """
    client = TestClient(app)
    headers = auth_headers(client, username="migrate_user")
    setup_course_with_material(client, headers, content=TLB_TEXT)

    migrate_mod = _load_migrate_module()
    monkeypatch.setattr(sys, "argv", ["migrate.py", "--dry-run"])

    ret = migrate_mod.main()
    captured = capsys.readouterr()

    assert ret == 0
    output = captured.out

    # The output should contain at least one numeric statistic beyond the
    # fixed placeholder text.  We look for patterns like
    # "materials_to_migrate=" or "chunks=" or "changed=".
    has_real_stat = any(
        keyword in output
        for keyword in (
            "materials_to_migrate",
            "chunks_to_normalise",
            "materials_count",
            "chunks_count",
            "would_migrate",
            "stats",
        )
    )
    assert has_real_stat, (
        f"--dry-run output does not contain real statistics. Output:\n{output}"
    )


def test_migration_sets_version_for_historical_materials(monkeypatch, tmp_path) -> None:
    """Migrations should create version 1 for historical materials.

    After running the migration, every material that existed before V3
    should have ``version=1`` (or a similar version marker).  The
    current migration does not add or populate a ``version`` column on
    the materials table.
    """
    client = TestClient(app)
    headers = auth_headers(client, username="migrate_user2")
    setup_course_with_material(client, headers, content=TLB_TEXT)

    # Simulate a historical material whose version was never set
    # (as would be the case for data created before the version column
    # was introduced).
    with engine.begin() as conn:
        conn.execute(text("UPDATE materials SET version = NULL"))

    # Verify the pre-condition: at least one material has NULL version.
    with engine.begin() as conn:
        null_count = conn.execute(
            text("SELECT COUNT(*) FROM materials WHERE version IS NULL")
        ).scalar()
    assert null_count > 0, "Pre-condition failed: no materials with NULL version"

    migrate_mod = _load_migrate_module()
    monkeypatch.setattr(sys, "argv", ["migrate.py"])
    migrate_mod.main()

    # After migration, every material should have version >= 1.
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM materials "
                "WHERE version IS NULL OR version < 1"
            )
        ).scalar()
    assert result == 0, (
        f"{result} materials have version < 1 or NULL — "
        f"historical materials should be set to version=1 by the migration"
    )


def test_second_migration_run_reports_zero_changes(
    monkeypatch, tmp_path, capsys
) -> None:
    """Second migration run should report changed=0 (idempotent).

    After running the migration once, a second run should report that
    zero rows were changed, confirming idempotency.
    """
    client = TestClient(app)
    headers = auth_headers(client, username="migrate_user3")
    setup_course_with_material(client, headers, content=TLB_TEXT)

    migrate_mod = _load_migrate_module()

    # First run.
    monkeypatch.setattr(sys, "argv", ["migrate.py"])
    migrate_mod.main()
    capsys.readouterr()  # discard first-run output

    # Second run.
    migrate_mod.main()
    second_output = capsys.readouterr().out

    # The second run should report changed=0 (or equivalent) somewhere
    # in its output, indicating no rows were modified.
    has_zero_change = any(
        keyword in second_output
        for keyword in (
            "changed=0",
            "changed: 0",
            "modified=0",
            "no changes",
            "already up to date",
            "nothing to migrate",
        )
    )
    assert has_zero_change, (
        f"Second migration run did not report 0 changes. Output:\n"
        f"{second_output}"
    )
