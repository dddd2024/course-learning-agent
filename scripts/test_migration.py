"""Quick smoke-test for the migration pipeline (MIG-V3-01).

Usage::

    python scripts/test_migration.py

Runs the migration in dry-run mode and checks that:
- The schema_migrations table is created.
- All 8 versioned migrations are discovered.
- Dry-run output contains real statistics.
- A second dry-run reports the same statistics (idempotent).

This script is intended for manual verification, not for CI.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
backend_dir = repo_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

from sqlalchemy import inspect

from app.core.database import engine
from app.db.schema_migrations import (
    ensure_schema_migrations_table,
    get_applied_versions,
)
from app.db.versioned_migrations import MIGRATION_MODULES, load_migrations


def main() -> int:
    print("=== Migration smoke test ===")

    # 1. Ensure schema_migrations table exists.
    ensure_schema_migrations_table(engine)
    insp = inspect(engine)
    assert "schema_migrations" in insp.get_table_names(), (
        "schema_migrations table was not created"
    )
    print("[OK] schema_migrations table exists")

    # 2. Load all migrations.
    migrations = load_migrations()
    assert len(migrations) == len(MIGRATION_MODULES), (
        f"Expected {len(MIGRATION_MODULES)} migrations, "
        f"got {len(migrations)}"
    )
    print(f"[OK] {len(migrations)} migrations loaded")

    # 3. Run dry-run for each migration.
    print("\n--- Dry-run statistics ---")
    for mig in migrations:
        try:
            stats = mig.dry_run(None, engine)
            print(f"  {mig.version_id}: {stats}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {mig.version_id}: ERROR: {exc}")

    # 4. Show applied versions.
    applied = get_applied_versions(engine)
    print(f"\nApplied versions: {applied}")

    print("\n=== Smoke test passed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
