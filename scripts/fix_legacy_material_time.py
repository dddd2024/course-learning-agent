#!/usr/bin/env python
"""Fix legacy naive-UTC datetime values in the materials table.

Before the timezone-aware UTC migration (commit 2c60dfa), Material
``uploaded_at`` was stored as a naive ``datetime.utcnow()`` value. SQLite
stored these as plain strings without timezone info, causing the frontend
to display times shifted by the local UTC offset (e.g. +08:00).

This script detects materials whose ``uploaded_at`` lacks timezone info
and re-stamps them as timezone-aware UTC. It defaults to **dry-run**
mode; pass ``--apply`` to actually write changes.

Usage:
    # Dry-run (prints what would change, writes nothing):
    python scripts/fix_legacy_material_time.py

    # Apply changes:
    python scripts/fix_legacy_material_time.py --apply

    # Use a custom database URL:
    python scripts/fix_legacy_material_time.py --db-url sqlite:///./dev.db --apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend is importable when run from the repo root.
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker


def _parse_naive_utc(value: str) -> datetime | None:
    """Try to parse a naive datetime string (SQLite format) as UTC.

    Returns None if the value is already timezone-aware or unparseable.
    """
    if not value:
        return None

    # Already timezone-aware (has +00:00 or similar) — skip.
    if "+" in value[-6:] or value.endswith("Z"):
        return None

    # Try common SQLite datetime formats.
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fix legacy naive-UTC datetime values in materials."
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (defaults to app settings).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes (default: dry-run).",
    )
    args = parser.parse_args()

    # Determine the database URL.
    if args.db_url:
        db_url = args.db_url
    else:
        from app.core.config import settings

        db_url = settings.DATABASE_URL

    print(f"Database: {db_url}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    engine = create_engine(db_url)
    insp = inspect(engine)

    if "materials" not in insp.get_table_names():
        print("Table 'materials' does not exist. Nothing to fix.")
        return 0

    # Fetch all uploaded_at values.
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, uploaded_at FROM materials ORDER BY id")
        ).fetchall()

    candidates = []
    for row in rows:
        mat_id = row[0]
        raw = row[1]
        if raw is None:
            continue
        # SQLite may return a string or a datetime object.
        if isinstance(raw, datetime):
            if raw.tzinfo is not None:
                continue  # already aware
            aware = raw.replace(tzinfo=timezone.utc)
        elif isinstance(raw, str):
            aware = _parse_naive_utc(raw)
            if aware is None:
                continue
        else:
            continue

        candidates.append((mat_id, str(raw), aware.isoformat()))

    if not candidates:
        print("No legacy naive-UTC datetime values found. All good.")
        return 0

    print(f"Found {len(candidates)} row(s) to fix:")
    for mat_id, old_val, new_val in candidates[:10]:
        print(f"  material_id={mat_id}: {old_val} -> {new_val}")
    if len(candidates) > 10:
        print(f"  ... and {len(candidates) - 10} more")

    if not args.apply:
        print("\nDry-run: no changes written. Re-run with --apply to fix.")
        return 0

    # Apply changes.
    with engine.begin() as conn:
        for mat_id, _, new_val in candidates:
            conn.execute(
                text(
                    "UPDATE materials SET uploaded_at = :val WHERE id = :id"
                ),
                {"val": new_val, "id": mat_id},
            )

    print(f"\nApplied: {len(candidates)} row(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
