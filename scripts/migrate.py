"""Safe, repeatable local migration entry point."""
from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    db_path = Path(str(engine.url.database or ""))
    if args.dry_run:
        print(f"dry-run: database={db_path}")
        print("would add compatibility columns and normalise historical task types")
        return 0
    if db_path.exists():
        backup = db_path.with_suffix(
            db_path.suffix + ".backup-" + datetime.now().strftime("%Y%m%d%H%M%S")
        )
        shutil.copy2(db_path, backup)
        print(f"backup={backup}")
    ensure_concept_compare_report_columns(engine)
    ensure_material_parse_columns(engine)
    ensure_first_round_columns(engine)
    with engine.begin() as conn:
        if "study_tasks" in inspect(engine).get_table_names():
            changed = conn.execute(text(
                "UPDATE study_tasks SET task_type='quiz' "
                "WHERE lower(task_type) IN ('practice','exercise','test')"
            )).rowcount
            print(f"normalised_task_types={changed}")
        if "material_chunks" in inspect(engine).get_table_names():
            copied_raw = conn.execute(text(
                "UPDATE material_chunks SET raw_text=text "
                "WHERE raw_text IS NULL OR raw_text=''"
            )).rowcount
            normalised_index = conn.execute(text(
                "UPDATE material_chunks SET is_indexable=1 "
                "WHERE is_indexable IS NULL"
            )).rowcount
            print(f"backfilled_chunk_raw_text={copied_raw}")
            print(f"normalised_chunk_indexability={normalised_index}")
    print("migration complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
