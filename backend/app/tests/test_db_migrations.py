"""Tests for the lightweight column migrator (no Alembic)."""
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect

from app.db.migrations import ensure_concept_compare_report_columns


def _make_old_reports_table(engine):
    """Create concept_compare_reports WITHOUT user_focus/evidence_hash."""
    metadata = MetaData()
    Table(
        "concept_compare_reports", metadata,
        Column("id", Integer, primary_key=True),
        Column("user_id", Integer),
        Column("source_node_id", Integer),
        Column("target_node_id", Integer),
        Column("report_json", String),
    )
    metadata.create_all(engine)


def test_ensure_columns_adds_missing_user_focus_and_evidence_hash():
    """旧库缺少两列时，迁移器必须补上。"""
    engine = create_engine("sqlite:///:memory:")
    _make_old_reports_table(engine)
    insp = inspect(engine)
    cols_before = {c["name"] for c in insp.get_columns("concept_compare_reports")}
    assert "user_focus" not in cols_before
    assert "evidence_hash" not in cols_before

    ensure_concept_compare_report_columns(engine)

    insp = inspect(engine)
    cols_after = {c["name"] for c in insp.get_columns("concept_compare_reports")}
    assert "user_focus" in cols_after
    assert "evidence_hash" in cols_after


def test_ensure_columns_idempotent_when_columns_already_present():
    """新库已有两列时，迁移器不得报错。"""
    from app.models.base import Base
    from app.models.concept_graph import ConceptCompareReport  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ConceptCompareReport.__table__])

    # 不应抛异常
    ensure_concept_compare_report_columns(engine)
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("concept_compare_reports")}
    assert "user_focus" in cols
    assert "evidence_hash" in cols


def test_ensure_columns_skips_when_table_absent():
    """表不存在时迁移器静默跳过（create_all 会后续建表）。"""
    engine = create_engine("sqlite:///:memory:")
    # 不建任何表，不应抛异常
    ensure_concept_compare_report_columns(engine)
