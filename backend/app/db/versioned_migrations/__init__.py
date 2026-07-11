"""Versioned data-migration package (MIG-V3-01).

Each module in this package defines a single migration with:

- ``version_id``: unique string identifier (e.g. ``"001_material_versions"``)
- ``description``: human-readable summary
- ``up(db, engine)``: applies the migration
- ``dry_run(db, engine) -> dict``: returns statistics about what *would* change

Migrations are applied in order and tracked in the ``schema_migrations``
table so re-running them is a no-op.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any, Protocol


class VersionedMigration(Protocol):
    """Protocol describing a versioned migration module."""

    version_id: str
    description: str

    def up(self, db: Any, engine: Any) -> None: ...
    def dry_run(self, db: Any, engine: Any) -> dict: ...


# Ordered list of migration module names. Adding a new migration means
# appending its module name here.
MIGRATION_MODULES = [
    "001_material_versions",
    "002_active_chunks",
    "003_knowledge_keys",
    "004_quiz_evidence",
    "005_citation_support",
    "006_agent_status",
    "007_plan_targets",
    "008_orphan_goals",
]


def load_migrations() -> list:
    """Import and return all migration modules in order."""
    migrations = []
    for name in MIGRATION_MODULES:
        mod = import_module(f"app.db.versioned_migrations.{name}")
        migrations.append(mod)
    return migrations
