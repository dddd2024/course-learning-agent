"""Regression tests for the stable page rebuild API contract."""
from app.services.page_asset_rebuild_contract import normalize_page_asset_rebuild_result


def test_existing_stable_contract_is_preserved() -> None:
    original = {
        "material_id": 3,
        "status": "ready",
        "reader_state": "fully_repaired",
        "expected_pages": 2,
        "ready_pages": 2,
        "missing_pages": 0,
        "page_asset_rebuild": {"status": "success"},
        "page_catalog_backfill": {
            "status": "success",
            "created": 2,
            "remaining_synthetic_page_numbers": [],
        },
        "error_code": None,
    }
    assert normalize_page_asset_rebuild_result(3, original) == original


def test_legacy_partial_coverage_is_not_reported_as_success() -> None:
    result = normalize_page_asset_rebuild_result(7, {
        "status": "partial",
        "expected_pages": 3,
        "ready_pages": 2,
        "missing_pages": 1,
        "synthetic_page_numbers": [3],
    })
    assert result["status"] == "readable_but_not_repaired"
    assert result["reader_state"] == "synthetic_fallback"
    assert result["page_asset_rebuild"]["status"] == "failed"
    assert result["page_catalog_backfill"]["status"] == "skipped"
    assert result["page_catalog_backfill"]["remaining_synthetic_page_numbers"] == [3]
    assert result["error_code"] == "PAGE_ASSET_REBUILD_INCOMPLETE"


def test_busy_legacy_result_uses_same_contract() -> None:
    result = normalize_page_asset_rebuild_result(11, {
        "status": "busy",
        "expected_pages": 0,
        "ready_pages": 0,
        "missing_pages": 0,
    })
    assert result["status"] == "failed"
    assert result["reader_state"] == "unavailable"
    assert result["page_asset_rebuild"]["status"] == "skipped"
    assert result["error_code"] == "PAGE_ASSET_REBUILD_BUSY"
