"""Tests for parse background task behavior.

Covers Task B of the reliability-windows-launcher plan:
- POST /materials/{id}/parse returns immediately with status=processing.
- The background task eventually sets ready/failed.
- Re-posting while processing returns current status without starting a
  second background task.
"""
from datetime import timedelta

from app.core.database import get_db
from app.core.timezone import utc_now
from app.models.general_error_log import ErrorLog
from app.models.material import Material
from app.tests.conftest import auth_headers, create_course, upload_material


def _test_db(client):
    return next(client.app.dependency_overrides[get_db]())


def test_parse_returns_processing_immediately(
    client, tmp_path, monkeypatch
) -> None:
    """POST /materials/{id}/parse returns status=processing without blocking."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client,
        headers,
        course_id,
        "notes.txt",
        ("操作系统管理硬件资源。" * 20).encode("utf-8"),
    )

    resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    # The endpoint returns processing immediately (background task runs later).
    assert body["status"] == "processing"


def test_parse_while_processing_returns_current_status(
    client, tmp_path, monkeypatch
) -> None:
    """Re-posting parse while processing returns current status, no duplicate task."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client, headers, course_id, "notes.txt", b"content"
    )

    # Force the material into processing state.
    db = _test_db(client)
    try:
        mat = db.query(Material).filter(Material.id == material_id).first()
        mat.status = "processing"
        mat.parse_started_at = utc_now()
        mat.parse_attempts = 1
        db.commit()
    finally:
        db.close()

    resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    # Already processing — return current status, don't start another task.
    assert body["status"] == "processing"


def test_parse_background_task_completes(
    client, tmp_path, monkeypatch
) -> None:
    """After the background task runs, the material reaches ready or failed."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client,
        headers,
        course_id,
        "notes.txt",
        ("操作系统管理硬件资源。" * 20).encode("utf-8"),
    )

    # Post parse — returns immediately with processing.
    resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing"

    # TestClient runs BackgroundTasks after the response is sent.
    # Re-fetch the material to see the final state.
    db = _test_db(client)
    try:
        mat = db.query(Material).filter(Material.id == material_id).first()
        assert mat.status in ("ready", "failed")
        if mat.status == "ready":
            assert mat.parse_attempts == 0  # reset on success
    finally:
        db.close()
