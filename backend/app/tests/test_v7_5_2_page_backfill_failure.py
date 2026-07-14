"""A readable legacy preview must not be reported as a completed repair."""
from __future__ import annotations

from app.core.config import settings
from app.models.material_page import MaterialPage
from app.services.material_page_asset_service import rebuild_page_assets
from app.tests.test_v7_5_2_page_asset_transaction import _setup_material


def test_backfill_failure_restores_old_assets_and_reports_partial_repair(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, version = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )
    db_session.query(MaterialPage).filter(MaterialPage.material_version_id == version.id).delete()
    db_session.commit()

    def fail_backfill(*args, **kwargs):
        raise RuntimeError("injected page catalogue failure")

    monkeypatch.setattr(
        "app.services.material_page_asset_service.backfill_missing_material_pages",
        fail_backfill,
    )
    result = rebuild_page_assets(db_session, material)

    assert result["status"] == "readable_but_not_repaired"
    assert result["reader_state"] == "synthetic_fallback"
    assert result["error_code"] == "PAGE_CATALOG_BACKFILL_FAILED"
    assert result["page_asset_rebuild"]["status"] == "restored_previous_assets"
    assert result["page_catalog_backfill"]["status"] == "failed"
    assert result["page_catalog_backfill"]["remaining_synthetic_page_numbers"] == [1, 2, 3]
    assert result["ready_pages"] == 3
    assert db_session.query(MaterialPage).filter(MaterialPage.material_version_id == version.id).count() == 0
