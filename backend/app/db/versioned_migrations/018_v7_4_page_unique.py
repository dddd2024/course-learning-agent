"""Lossless, transactional material_pages uniqueness migration."""
from __future__ import annotations

import hashlib
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "018_v7_4_page_unique"
description = "Enforce UNIQUE(material_version_id, page_no) without data loss."
SNAPSHOT_FIELDS = ["id", "material_id", "material_version_id", "page_no", "page_type", "parser_version", "raw_text", "clean_text", "blocks_json", "decisions_json", "created_at", "updated_at"]


def _compute_snapshot(conn, table: str = "material_pages") -> str:
    """Hash all migration fields using the caller's transaction connection."""
    # Compatibility for read-only callers from pre-V7.4.3 tests.  The
    # migration itself always supplies its active transaction connection.
    if isinstance(conn, Engine):
        with conn.connect() as read_conn:
            return _compute_snapshot(read_conn, table)
    digest = hashlib.sha256()
    rows = conn.execute(text(f"SELECT {', '.join(SNAPSHOT_FIELDS)} FROM {table} ORDER BY id")).fetchall()
    for row in rows:
        digest.update("|".join("\0NULL" if value is None else str(value) for value in row).encode("utf-8"))
        digest.update(b"\n")
    digest.update(f"rows={len(rows)}|fields={'|'.join(SNAPSHOT_FIELDS)}".encode("utf-8"))
    return digest.hexdigest()


def _has_unique_constraint(engine: Engine) -> bool:
    """Use SQLite's index metadata; never infer a constraint from SQL text."""
    if "material_pages" not in inspect(engine).get_table_names():
        return True
    with engine.connect() as conn:
        for index in conn.execute(text("PRAGMA index_list('material_pages')")).mappings():
            if not index["unique"]:
                continue
            columns = conn.execute(text(f"PRAGMA index_xinfo('{index['name']}')")).mappings().all()
            keys = [item["name"] for item in sorted(columns, key=lambda item: item["seqno"]) if item["key"]]
            if keys == ["material_version_id", "page_no"]:
                return True
    return False


def dry_run(db, engine: Engine) -> dict:
    if "material_pages" not in inspect(engine).get_table_names():
        return {"duplicates": 0, "already_has_constraint": True, "leftover_temp_table": False}
    with engine.connect() as conn:
        duplicates = conn.execute(text("SELECT COUNT(*) FROM (SELECT 1 FROM material_pages WHERE material_version_id IS NOT NULL GROUP BY material_version_id, page_no HAVING COUNT(*) > 1)")).scalar_one()
        leftover = conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='material_pages_new'")).scalar() is not None
    return {"duplicates": duplicates, "already_has_constraint": _has_unique_constraint(engine), "leftover_temp_table": leftover}


def _preserved_ddl(conn) -> list[str]:
    rows = conn.execute(text("""
        SELECT sql FROM sqlite_master
        WHERE tbl_name='material_pages' AND type IN ('index', 'trigger') AND sql IS NOT NULL
        ORDER BY type, name
    """)).scalars().all()
    return list(rows)


def _run_stage(stage: str, conn) -> None:
    """Named migration seam for deterministic fault-injection tests.

    Production calls are intentionally no-ops. Tests monkeypatch this narrow
    seam to raise at a transaction boundary and prove that SQLite rolls the
    entire table rebuild back rather than leaving a half-migrated table.
    """
    _ = (stage, conn)


def up(db, engine: Engine) -> None:
    if "material_pages" not in inspect(engine).get_table_names() or _has_unique_constraint(engine):
        return
    with engine.begin() as conn:
        # pysqlite's legacy transaction mode may defer BEGIN until the first
        # DML statement. SQLite DDL executed before that point is autocommitted
        # and leaves ``material_pages_new`` behind after a failure. Force a
        # real transaction before CREATE/DROP/ALTER so this rebuild is atomic.
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        if conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='material_pages_new'")).scalar():
            raise RuntimeError("Leftover table 'material_pages_new' detected; refusing migration.")
        duplicates = conn.execute(text("""
            SELECT material_version_id, page_no, COUNT(*) FROM material_pages
            WHERE material_version_id IS NOT NULL GROUP BY material_version_id, page_no HAVING COUNT(*) > 1
        """)).fetchall()
        if duplicates:
            raise RuntimeError(f"Cannot add UNIQUE constraint; duplicate keys: {duplicates[:5]}")
        before = _compute_snapshot(conn)
        ddl = _preserved_ddl(conn)
        conn.execute(text("""
            CREATE TABLE material_pages_new (
              id INTEGER PRIMARY KEY,
              material_id INTEGER NOT NULL REFERENCES materials(id),
              material_version_id INTEGER REFERENCES material_versions(id),
              page_no INTEGER NOT NULL, page_type VARCHAR(30) NOT NULL DEFAULT 'text',
              parser_version VARCHAR(32) NOT NULL DEFAULT 'legacy', raw_text TEXT, clean_text TEXT,
              blocks_json TEXT, decisions_json TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(material_version_id, page_no)
            )
        """))
        _run_stage("create", conn)
        conn.execute(text(f"INSERT INTO material_pages_new ({', '.join(SNAPSHOT_FIELDS)}) SELECT {', '.join(SNAPSHOT_FIELDS)} FROM material_pages"))
        _run_stage("copy", conn)
        if _compute_snapshot(conn, "material_pages_new") != before:
            raise RuntimeError("Temporary table snapshot mismatch; rolling back.")
        _run_stage("snapshot_temp", conn)
        conn.execute(text("DROP TABLE material_pages"))
        _run_stage("drop", conn)
        conn.execute(text("ALTER TABLE material_pages_new RENAME TO material_pages"))
        _run_stage("rename", conn)
        for statement in ddl:
            conn.execute(text(statement))
        _run_stage("restore_ddl", conn)
        violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        if violations:
            raise RuntimeError(f"Foreign-key check failed: {violations}")
        _run_stage("foreign_key_check", conn)
        if _compute_snapshot(conn) != before:
            raise RuntimeError("Final snapshot mismatch before commit; rolling back.")
        _run_stage("snapshot_final", conn)
