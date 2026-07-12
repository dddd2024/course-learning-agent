"""Tests for timezone-aware serialization of Material timestamps.

SQLite's SQLAlchemy dialect strips tzinfo from DateTime(timezone=True)
columns on read, so the API used to emit naive ISO strings (no offset).
The browser then treated them as local time, producing an 8-hour skew
for UTC+8 clients. These tests lock in the fix: every timestamp
returned by the materials API MUST carry an explicit UTC offset.
"""
from datetime import datetime

from app.tests.conftest import auth_headers, create_course, upload_material, run_pending_parse_jobs


def _assert_tz_aware(iso_str: str) -> None:
    """A timestamp string must parse to a tz-aware datetime."""
    assert isinstance(iso_str, str), f"expected str, got {type(iso_str)}"
    dt = datetime.fromisoformat(iso_str)
    assert dt.tzinfo is not None, (
        f"timestamp must be tz-aware (have an offset), got: {iso_str!r}"
    )


def test_list_materials_returns_tz_aware_uploaded_at(
    client, tmp_path, monkeypatch
) -> None:
    """GET /courses/{id}/materials returns uploaded_at with a UTC offset."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    upload_material(client, headers, course_id, "notes.txt", b"hello world")

    resp = client.get(f"/api/v1/courses/{course_id}/materials", headers=headers)
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    _assert_tz_aware(item["uploaded_at"])


def test_parse_response_exposes_tz_aware_parse_times(
    client, tmp_path, monkeypatch
) -> None:
    """After a parse, parse_started_at / parse_finished_at carry an offset."""
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

    parse_resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert parse_resp.status_code == 200
    run_pending_parse_jobs(client)

    resp = client.get(f"/api/v1/courses/{course_id}/materials", headers=headers)
    item = next(m for m in resp.json()["items"] if m["id"] == material_id)
    _assert_tz_aware(item["uploaded_at"])
    # Background task runs synchronously under TestClient, so by now the
    # parse has finished and both parse timestamps are populated.
    assert item["parse_started_at"] is not None
    _assert_tz_aware(item["parse_started_at"])
    assert item["parse_finished_at"] is not None
    _assert_tz_aware(item["parse_finished_at"])
