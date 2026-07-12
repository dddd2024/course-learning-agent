"""Idempotently rebuild the local SQLite material FTS index."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.core.database import SessionLocal
from app.retrieval.search import rebuild_fts_index

if __name__ == "__main__":
    db = SessionLocal()
    try:
        rebuild_fts_index(db)
        print("FTS index rebuilt")
    finally:
        db.close()
