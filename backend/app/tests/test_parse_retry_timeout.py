"""Tests for parse retry, timeout recovery, and error logging.

Covers the error-log/parse-reliability plan:
- list_materials auto-corrects a processing material past the timeout
  threshold to failed and writes an error_log.
- parse_material retries on a retryable error (parse_file patched to fail
  twice then succeed) and ends ready with parse_attempts reset.
- parse_material that always fails ends failed with parse_attempts ==
  max_retries and an error_log row.
- re-parse failure with existing chunks keeps ready + warning + error_log.
"""
from datetime import timedelta

from app.core.database import get_db
from app.core.timezone import utc_now
from app.models.general_error_log import ErrorLog
from app.models.material import Material
from app.tests.conftest import auth_headers, create_course, upload_material


def _test_db(client):
    return next(client.app.dependency_overrides[get_db]())


def _force_status(db, material_id, *, status, started_at=None, attempts=0):
    mat = db.query(Material).filter(Material.id == material_id).first()
    mat.status = status
    mat.parse_started_at = started_at
    mat.parse_attempts = attempts
    db.commit()
    return mat


# ---------------------------------------------------------------------------
# Timeout recovery in list_materials
# ---------------------------------------------------------------------------


def test_list_materials_recovers_processing_timeout(client, tmp_path, monkeypatch) -> None:
    """A processing material past the timeout becomes failed + an error log."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    # Shrink the timeout so the test does not wait 300s.
    monkeypatch.setattr("app.api.v1.endpoints.materials.PARSE_TIMEOUT_SECONDS", 0)

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client, headers, course_id, "notes.txt", b"content"
    )

    db = _test_db(client)
    try:
        _force_status(
            db,
            material_id,
            status="processing",
            started_at=utc_now() - timedelta(seconds=10),
            attempts=1,
        )
    finally:
        db.close()

    # list_materials runs the timeout check before returning.
    resp = client.get(
        f"/api/v1/courses/{course_id}/materials", headers=headers
    )
    assert resp.status_code == 200
    item = next(m for m in resp.json()["items"] if m["id"] == material_id)
    assert item["status"] == "failed"

    # An error_log row was written for the timeout.
    logs = client.get("/api/v1/logs?category=parse", headers=headers).json()
    assert logs["total"] >= 1
    assert any("超时" in i["message"] or "timeout" in i["message"].lower()
               for i in logs["items"])


# ---------------------------------------------------------------------------
# parse retry
# ---------------------------------------------------------------------------


def test_parse_retries_then_succeeds(client, tmp_path, monkeypatch) -> None:
    """parse_material retries a retryable error and ends ready."""
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

    # parse_file fails twice then succeeds.
    calls = {"n": 0}
    real_parse_file = None
    from app.retrieval import parsers as _parsers

    real_parse_file = _parsers.parse_file

    def flaky_parse(path, file_type):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("temporary read error")
        return real_parse_file(path, file_type)

    monkeypatch.setattr("app.services.material_parser.parse_file", flaky_parse)

    resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    # Background task: endpoint returns processing immediately.
    assert body["status"] == "processing"

    # After the background task completes, check the final state.
    assert calls["n"] == 3  # 2 failures + 1 success
    # No error log on success.
    logs = client.get("/api/v1/logs?category=parse", headers=headers).json()
    # retries happened, so warning-level logs may exist for the failed
    # attempts, but the material ended ready.
    db = _test_db(client)
    try:
        mat = db.query(Material).filter(Material.id == material_id).first()
        assert mat.status == "ready"
        assert mat.parse_attempts == 0  # reset on success
    finally:
        db.close()


def test_parse_always_fails_ends_failed_with_log(
    client, tmp_path, monkeypatch
) -> None:
    """A material that always fails parse ends failed with an error log."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client, headers, course_id, "notes.txt", b"content"
    )

    def always_fail(path, file_type):
        raise RuntimeError("PDF text extraction empty")

    monkeypatch.setattr("app.services.material_parser.parse_file", always_fail)

    resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert resp.status_code == 200
    # Background task: endpoint returns processing immediately.
    body = resp.json()
    assert body["status"] == "processing"

    db = _test_db(client)
    try:
        mat = db.query(Material).filter(Material.id == material_id).first()
        assert mat.status == "failed"
        assert mat.parse_attempts == 3  # max retries
        assert mat.last_parse_error is not None
    finally:
        db.close()

    # An error log was written.
    logs = client.get("/api/v1/logs?category=parse", headers=headers).json()
    assert logs["total"] >= 1
    last = logs["items"][0]
    assert last["level"] == "error"
    assert last["retry_count"] == 3
    assert last["max_retries"] == 3


def test_reparse_failure_with_old_chunks_keeps_ready_warning(
    client, tmp_path, monkeypatch
) -> None:
    """Re-parse failure when old chunks exist keeps ready + warning + log."""
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

    # First parse succeeds so chunks exist.
    ok = client.post(f"/api/v1/materials/{material_id}/parse", headers=headers)
    assert ok.status_code == 200
    # Background task: endpoint returns processing immediately.
    assert ok.json()["status"] == "processing"

    # Second parse always fails.
    def always_fail(path, file_type):
        raise RuntimeError("re-parse failure")

    monkeypatch.setattr("app.services.material_parser.parse_file", always_fail)

    resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert resp.status_code == 200
    # Background task: endpoint returns processing immediately.
    body = resp.json()
    assert body["status"] == "processing"

    db = _test_db(client)
    try:
        mat = db.query(Material).filter(Material.id == material_id).first()
        assert mat.status == "ready"
        assert mat.error_message is not None  # stale-ready warning
    finally:
        db.close()

    # A warning/error log was written for the re-parse failure.
    logs = client.get("/api/v1/logs?category=parse", headers=headers).json()
    assert logs["total"] >= 1


# ---------------------------------------------------------------------------
# Parse timeout default
# ---------------------------------------------------------------------------


def test_default_parse_timeout_is_600_seconds() -> None:
    """The default parse timeout is 600s (generous for slow PDFs).

    Regression guard: a single textbook-chapter PDF can take longer than
    the old 300s under pypdf; declaring it timed out mid-parse flips the
    status to failed while the background task is still running. 600s
    keeps the crashed-worker recovery while avoiding false timeouts on
    large but legitimately-running parses.
    """
    from app.api.v1.endpoints import materials as materials_endpoint

    assert materials_endpoint.PARSE_TIMEOUT_SECONDS == 600
