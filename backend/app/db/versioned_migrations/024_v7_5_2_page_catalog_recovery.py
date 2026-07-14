"""Safely recover legacy page catalogues and material external identities.

This migration deliberately uses an explicit ``materials`` schema.  SQLite
emits ``PRIMARY KEY (id)`` for SQLAlchemy's table-level primary key, so editing
``sqlite_master.sql`` with a regexp is neither safe nor portable.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.models.material import Material
from app.services.material_page_asset_service import backfill_missing_material_pages
from app.services.material_page_catalog_service import resolve_expected_page_numbers

version_id = "024_v7_5_2_page_catalog_recovery"
description = "Safely rebuild legacy materials and recover page catalogues"
TEMP_TABLE = "materials__v752_new"


@dataclass(frozen=True)
class MaterialsSchemaSnapshot:
    columns: tuple[str, ...]
    row_count: int
    max_id: int
    indexes: tuple[str, ...]
    foreign_keys: tuple[tuple, ...]
    schema_hash: str
    has_autoincrement: bool
    has_public_id: bool
    public_id_not_null: bool
    public_id_unique: bool
    public_id_null_rows: int
    public_id_duplicate_rows: int

    @property
    def public_id_exists(self) -> bool:
        """Name used by the audit report; keep the older field compatible."""
        return self.has_public_id


def inspect_materials_schema(conn: Connection) -> MaterialsSchemaSnapshot:
    table_sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='materials'")).scalar()
    if not table_sql:
        return MaterialsSchemaSnapshot((), 0, 0, (), (), "", False, False, False, False, 0, 0)
    column_rows = conn.execute(text("PRAGMA table_info(materials)")).fetchall()
    columns = tuple(row[1] for row in column_rows)
    public_info = next((row for row in column_rows if row[1] == "public_id"), None)
    public_not_null = bool(public_info and public_info[3])
    unique = False
    for index in conn.execute(text("PRAGMA index_list(materials)")).fetchall():
        if index[2] and [row[2] for row in conn.execute(text(f"PRAGMA index_info('{index[1]}')")).fetchall()] == ["public_id"]:
            unique = True
    indexes = tuple(
        row[0] for row in conn.execute(text("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='materials' AND sql IS NOT NULL")).fetchall()
    )
    foreign_keys = tuple(tuple(row) for row in conn.execute(text("PRAGMA foreign_key_list(materials)")).fetchall())
    row_count = int(conn.execute(text("SELECT COUNT(*) FROM materials")).scalar_one())
    max_id = int(conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM materials")).scalar_one())
    null_rows = duplicate_rows = 0
    if "public_id" in columns:
        null_rows = int(conn.execute(text("SELECT COUNT(*) FROM materials WHERE public_id IS NULL OR TRIM(public_id) = ''")).scalar_one())
        duplicate_rows = int(conn.execute(text("SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(*) AS n FROM materials WHERE public_id IS NOT NULL AND TRIM(public_id) <> '' GROUP BY public_id HAVING n > 1)" )).scalar_one())
    return MaterialsSchemaSnapshot(
        columns=columns, row_count=row_count, max_id=max_id, indexes=indexes,
        foreign_keys=foreign_keys, schema_hash=sha256(table_sql.encode("utf-8")).hexdigest(),
        has_autoincrement="AUTOINCREMENT" in table_sql.upper(), has_public_id="public_id" in columns,
        public_id_not_null=public_not_null, public_id_unique=unique,
        public_id_null_rows=null_rows, public_id_duplicate_rows=duplicate_rows,
    )


def create_materials_v752_table(conn: Connection) -> None:
    conn.execute(text(f"""
        CREATE TABLE {TEMP_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_id VARCHAR(36) NOT NULL,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            filename VARCHAR(255) NOT NULL,
            file_type VARCHAR(20) NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            status VARCHAR(30),
            version INTEGER,
            active_version_id INTEGER,
            error_message TEXT,
            uploaded_at DATETIME,
            created_at DATETIME,
            updated_at DATETIME,
            parse_started_at DATETIME,
            parse_finished_at DATETIME,
            parse_attempts INTEGER NOT NULL DEFAULT 0,
            last_parse_error TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(course_id) REFERENCES courses(id),
            FOREIGN KEY(active_version_id) REFERENCES material_versions(id),
            UNIQUE(public_id)
        )
    """))


def copy_materials_rows(conn: Connection, snapshot: MaterialsSchemaSnapshot) -> None:
    supported = [
        "id", "user_id", "course_id", "filename", "file_type", "file_path", "status", "version",
        "active_version_id", "error_message", "uploaded_at", "created_at", "updated_at",
        "parse_started_at", "parse_finished_at", "parse_attempts", "last_parse_error",
    ]
    source_columns = [column for column in supported if column in snapshot.columns]
    select_columns = (["public_id"] if snapshot.has_public_id else []) + source_columns
    rows = conn.execute(text(f"SELECT {', '.join(select_columns)} FROM materials")).mappings().all()
    target_columns = ["id", "public_id", *source_columns[1:]]
    params = []
    seen: set[str] = set()
    for row in rows:
        payload = {column: row[column] for column in source_columns}
        # Preserve an already-issued external identity during a second schema
        # repair.  Only genuinely old rows receive a new UUID.
        candidate = str(row.get("public_id") or "").strip()
        payload["public_id"] = candidate if candidate and candidate not in seen else str(uuid4())
        seen.add(payload["public_id"])
        params.append(payload)
    if params:
        names = ", ".join(target_columns)
        binds = ", ".join(f":{column}" for column in target_columns)
        conn.execute(text(f"INSERT INTO {TEMP_TABLE} ({names}) VALUES ({binds})"), params)


def restore_material_indexes(conn: Connection, snapshot: MaterialsSchemaSnapshot) -> None:
    for statement in snapshot.indexes:
        conn.execute(text(statement))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_materials_public_id ON materials(public_id)"))


def validate_materials_rebuild(conn: Connection, before: MaterialsSchemaSnapshot) -> None:
    after = inspect_materials_schema(conn)
    if after.row_count != before.row_count:
        raise RuntimeError(f"materials row count changed: {before.row_count} -> {after.row_count}")
    if not after.has_autoincrement or not after.has_public_id or not after.public_id_not_null or not after.public_id_unique:
        raise RuntimeError("materials rebuild did not create AUTOINCREMENT/public_id")
    if after.foreign_keys != before.foreign_keys:
        raise RuntimeError("materials foreign keys changed during rebuild")


def _set_future_id_floor(conn: Connection) -> None:
    # SQLite cannot recover a high-water mark deleted before this migration.
    # It can, however, prevent reuse of every ID allocated after the rebuild.
    maximum = int(conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM materials")).scalar_one())
    conn.execute(text("DELETE FROM sqlite_sequence WHERE name='materials'"))
    conn.execute(text("INSERT INTO sqlite_sequence(name, seq) VALUES ('materials', :seq)"), {"seq": maximum})


def _rebuild_materials_for_autoincrement(engine: Engine) -> None:
    with engine.connect() as conn:
        before = inspect_materials_schema(conn)
        needs_rebuild = (
            not before.columns or not before.has_autoincrement or not before.has_public_id
            or not before.public_id_not_null or not before.public_id_unique
        )
        if not needs_rebuild:
            return
        conn.commit()
        foreign_keys = int(conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one())
        # The PRAGMA read starts SQLAlchemy's implicit transaction.  Finish it
        # before beginning the single atomic schema-copy transaction below.
        conn.commit()
        if foreign_keys:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        try:
            transaction = conn.begin()
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS {TEMP_TABLE}"))
                create_materials_v752_table(conn)
                copy_materials_rows(conn, before)
                copied = int(conn.execute(text(f"SELECT COUNT(*) FROM {TEMP_TABLE}")).scalar_one())
                if copied != before.row_count:
                    raise RuntimeError(f"materials copy count mismatch: {before.row_count} -> {copied}")
                conn.execute(text("DROP TABLE materials"))
                conn.execute(text(f"ALTER TABLE {TEMP_TABLE} RENAME TO materials"))
                restore_material_indexes(conn, before)
                _set_future_id_floor(conn)
                validate_materials_rebuild(conn, before)
                transaction.commit()
            except Exception:
                transaction.rollback()
                raise
        except Exception:
            cleanup = conn.begin()
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS {TEMP_TABLE}"))
                cleanup.commit()
            except Exception:
                cleanup.rollback()
            raise
        finally:
            if foreign_keys:
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.commit()
        violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        if violations:
            raise RuntimeError(f"foreign_key_check failed: {violations}")


def _ensure_public_ids(engine: Engine) -> int:
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(materials)")).fetchall()}
        if "public_id" not in columns:
            conn.execute(text("ALTER TABLE materials ADD COLUMN public_id VARCHAR(36)"))
        rows = conn.execute(text("SELECT id FROM materials WHERE public_id IS NULL OR public_id = ''")).fetchall()
        for (material_id,) in rows:
            conn.execute(text("UPDATE materials SET public_id=:public_id WHERE id=:id"), {"id": material_id, "public_id": str(uuid4())})
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_materials_public_id ON materials(public_id)"))
        return len(rows)


def _legacy_pdf_materials(session: Session):
    return session.query(Material).filter(Material.file_type == "pdf", Material.active_version_id.isnot(None)).all()


def _catalog_stats(engine: Engine) -> dict:
    """Read only legacy-compatible columns for dry-run reporting.

    ``dry_run`` is invoked before the schema mutation, so it cannot load the
    current ORM model (which intentionally already requires ``public_id``).
    This is conservative: it counts pages represented by assets but lacking a
    durable page row; PDF page-count discovery remains part of ``up``.
    """
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        required = {"materials", "material_page_assets", "material_pages"}
        if not required.issubset(tables):
            return {"materials_scanned": 0, "materials_with_missing_pages": 0, "missing_page_rows": 0}
        rows = conn.execute(text("""
            SELECT a.material_id, a.material_version_id, a.page_no
            FROM material_page_assets AS a
            JOIN materials AS m ON m.id = a.material_id
            LEFT JOIN material_pages AS p
              ON p.material_id = a.material_id
             AND p.material_version_id = a.material_version_id
             AND p.page_no = a.page_no
            WHERE m.file_type = 'pdf'
              AND m.active_version_id IS NOT NULL
              AND p.id IS NULL
        """)).fetchall()
        scanned = int(conn.execute(text("""
            SELECT COUNT(*) FROM materials
            WHERE file_type = 'pdf' AND active_version_id IS NOT NULL
        """)).scalar_one())
    affected = len({(row[0], row[1]) for row in rows})
    return {"materials_scanned": scanned, "materials_with_missing_pages": affected, "missing_page_rows": len(rows)}


def dry_run(db, engine: Engine) -> dict:
    with engine.connect() as conn:
        snapshot = inspect_materials_schema(conn)
    stats = _catalog_stats(engine)
    stats.update({
        "material_autoincrement_missing": not snapshot.has_autoincrement,
        "public_id_column_missing": not snapshot.has_public_id,
        "public_id_exists": snapshot.public_id_exists,
        "public_id_missing": not snapshot.has_public_id,
        "public_id_not_null_missing": not snapshot.public_id_not_null,
        "public_id_unique_missing": not snapshot.public_id_unique,
        "public_id_null_rows": snapshot.public_id_null_rows,
        "public_id_duplicate_rows": snapshot.public_id_duplicate_rows,
        "would_change": stats["missing_page_rows"] + int(not snapshot.has_autoincrement) + int(not snapshot.has_public_id) + int(not snapshot.public_id_not_null) + int(not snapshot.public_id_unique) + snapshot.public_id_null_rows + snapshot.public_id_duplicate_rows,
    })
    return stats


def up(db, engine: Engine) -> None:
    _rebuild_materials_for_autoincrement(engine)
    _ensure_public_ids(engine)
    session = Session(bind=engine)
    try:
        for material in _legacy_pdf_materials(session):
            expected = resolve_expected_page_numbers(session, material)["expected_page_numbers"]
            if expected:
                backfill_missing_material_pages(session, material, page_numbers=expected)
        session.commit()
    except Exception:
        session.rollback(); raise
    finally:
        session.close()
