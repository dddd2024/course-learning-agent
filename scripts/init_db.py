"""Initialise the database by creating all registered tables.

Run from the ``backend`` directory so that ``app`` is importable::

    python ../scripts/init_db.py

The script makes the backend package importable regardless of the current
working directory, so it also works as ``python scripts/init_db.py`` from
the repository root.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _ensure_backend_on_path() -> None:
    """Make the ``backend`` package importable from any CWD.

    The script lives in ``<repo>/scripts`` and the app package in
    ``<repo>/backend``, so we add ``<repo>/backend`` to ``sys.path``.
    """
    here = Path(__file__).resolve()
    repo_root = here.parent.parent
    backend_dir = repo_root / "backend"
    if backend_dir.is_dir():
        for path in (str(backend_dir), str(repo_root)):
            if path not in sys.path:
                sys.path.insert(0, path)


_ensure_backend_on_path()

from app.core.database import engine  # noqa: E402
from app.models import Base  # noqa: E402
# Importing the models package ensures every registered model is attached to
# ``Base.metadata`` before ``create_all`` runs. Concrete models will be added
# to ``app.models`` as the project grows.


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # Legacy-DB compat: add user_focus/evidence_hash to existing
    # concept_compare_reports tables that predate v3. create_all does not
    # alter existing tables, so we patch them explicitly.
    from app.db.migrations import ensure_concept_compare_report_columns

    ensure_concept_compare_report_columns(engine)
    print("数据库表已创建（如已存在则跳过）。")


if __name__ == "__main__":
    init_db()
