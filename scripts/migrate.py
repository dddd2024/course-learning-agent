"""Safe, repeatable local migration entry point (MIG-V3-01).

Supports:
- ``--dry-run``: run all ``dry_run()`` functions, output JSON statistics
  with before/after/changed/skipped/legacy/errors. Does NOT modify DB.
- ``--json PATH``: write JSON output to the given file.
- ``--legacy``: also run the old-style idempotent column migrations.

Versioned migrations are tracked in the ``schema_migrations`` table so
re-running them is a no-op (idempotent). The SQLite database is backed
up automatically before any migration is applied.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
backend_dir = repo_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
# The default SQLite URL is relative (``./course_assistant.db``). Make the
# migration target the same database as uvicorn, regardless of where the
# operator launches this repository-level script from.
os.chdir(backend_dir)

from sqlalchemy import inspect, text

from app.core.database import engine
from app.db.migrations import (
    ensure_concept_compare_report_columns,
    ensure_first_round_columns,
    ensure_material_parse_columns,
)
from app.db.schema_migrations import (
    ensure_schema_migrations_table,
    get_applied_versions,
    is_applied,
    record_version,
)
from app.db.versioned_migrations import load_migrations


def _backup_database(db_path: Path) -> Path | None:
    """Copy the SQLite DB file to a timestamped backup."""
    if db_path.exists():
        backup = db_path.with_suffix(
            db_path.suffix + ".backup-" + datetime.now().strftime("%Y%m%d%H%M%S")
        )
        shutil.copy2(db_path, backup)
        print(f"backup={backup}")
        return backup
    return None


def _run_legacy_migrations(engine) -> int:
    """Run the old-style idempotent column migrations.

    Returns the number of changes made (best-effort).
    """
    ensure_concept_compare_report_columns(engine)
    ensure_material_parse_columns(engine)
    ensure_first_round_columns(engine)
    changed = 0
    with engine.begin() as conn:
        if "study_tasks" in inspect(engine).get_table_names():
            changed += conn.execute(text(
                "UPDATE study_tasks SET task_type='quiz' "
                "WHERE lower(task_type) IN ('practice','exercise','test')"
            )).rowcount
        if "material_chunks" in inspect(engine).get_table_names():
            changed += conn.execute(text(
                "UPDATE material_chunks SET raw_text=text "
                "WHERE raw_text IS NULL OR raw_text=''"
            )).rowcount
            changed += conn.execute(text(
                "UPDATE material_chunks SET is_indexable=1 "
                "WHERE is_indexable IS NULL"
            )).rowcount
    return changed


def _run_dry_run(engine) -> dict:
    """Run all dry_run functions and collect statistics.

    Even already-applied migrations have their ``dry_run()`` called so
    the operator can see what *would* change (e.g. materials with NULL
    version that a re-run would fix).  Already-applied migrations are
    counted in ``skipped`` but their stats are still included in
    ``before`` so the output always contains real statistics.
    """
    migrations = load_migrations()
    stats: dict = {
        "before": {},
        "after": {},
        "changed": 0,
        "skipped": 0,
        "legacy": 0,
        "errors": [],
    }
    applied = get_applied_versions(engine)
    for mig in migrations:
        try:
            mig_stats = mig.dry_run(None, engine)
            stats["before"][mig.version_id] = mig_stats
            if mig.version_id in applied:
                stats["skipped"] += 1
            else:
                would_change = mig_stats.get("would_change", 0)
                stats["changed"] += would_change
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append({
                "version": mig.version_id,
                "error": str(exc),
            })
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run database migrations (MIG-V3-01)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run all dry_run() functions and output statistics without "
             "modifying the database.",
    )
    parser.add_argument(
        "--json", type=str, default=None,
        help="Write JSON output to the given file path.",
    )
    parser.add_argument(
        "--legacy", action="store_true", default=True,
        help="Also run old-style idempotent column migrations (default).",
    )
    args = parser.parse_args()

    db_path = Path(str(engine.url.database or ""))

    # Ensure the schema_migrations tracking table exists.
    ensure_schema_migrations_table(engine)

    # ------------------------------------------------------------------
    # Dry-run mode: collect statistics, output JSON, do NOT modify DB.
    # ------------------------------------------------------------------
    if args.dry_run:
        stats = _run_dry_run(engine)
        stats["database"] = str(db_path)
        output = json.dumps(stats, indent=2, default=str)
        print(output)
        if args.json:
            Path(args.json).write_text(output, encoding="utf-8")
        return 0

    # ------------------------------------------------------------------
    # Apply mode: backup, run legacy + versioned migrations.
    # ------------------------------------------------------------------
    _backup_database(db_path)

    # Legacy migrations (idempotent column additions + normalisations).
    legacy_changed = 0
    if args.legacy:
        legacy_changed = _run_legacy_migrations(engine)
        print(f"legacy_changed={legacy_changed}")

    # Versioned migrations.
    migrations = load_migrations()
    applied = get_applied_versions(engine)
    changed_total = 0
    skipped = 0
    errors: list[dict] = []

    for mig in migrations:
        is_already_applied = mig.version_id in applied
        # Always check dry_run() so we can detect pending data fixes
        # even for already-applied migrations (e.g. materials whose
        # version was set back to NULL by a later operation).
        try:
            mig_stats = mig.dry_run(None, engine)
            would_change = mig_stats.get("would_change", 0)
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "version": mig.version_id,
                "error": str(exc),
            })
            print(f"error {mig.version_id}: {exc}")
            raise

        if is_already_applied and would_change == 0:
            print(f"skip {mig.version_id} (already applied, no pending changes)")
            skipped += 1
            continue

        if is_already_applied:
            print(
                f"re-running {mig.version_id} "
                f"(already applied but {would_change} pending data fixes)"
            )
        else:
            print(f"running {mig.version_id}")

        try:
            # Apply the migration in a transaction.
            mig.up(None, engine)

            # Record the version (only needed for first application,
            # but INSERT OR IGNORE makes this safe to call again).
            record_version(engine, mig.version_id)

            changed_total += would_change
            print(f"{mig.version_id}: changed={would_change}")
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "version": mig.version_id,
                "error": str(exc),
            })
            print(f"error {mig.version_id}: {exc}")
            # Re-raise so the operator knows something went wrong.
            raise

    print(f"changed={changed_total}")
    print(f"skipped={skipped}")
    if errors:
        print(f"errors={len(errors)}")
    print("migration complete")

    # Optionally write JSON output.
    if args.json:
        result = {
            "changed": changed_total,
            "skipped": skipped,
            "legacy_changed": legacy_changed,
            "errors": errors,
        }
        Path(args.json).write_text(
            json.dumps(result, indent=2, default=str),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
