"""Migrate legacy MaterialImage rows that have no material_version_id."""
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

from app.core.database import SessionLocal
from app.services.material_image_migration_service import migrate_legacy_images


def migrate() -> dict:
    db = SessionLocal()
    try:
        return migrate_legacy_images(db, commit=True)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print(json.dumps(migrate(), ensure_ascii=False, indent=2))
