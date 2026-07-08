"""Tests for upload failure cleanup and error logging.

Covers Task A of the reliability-windows-launcher plan:
- Unsupported file type writes an ErrorLog(category=upload).
- Oversized file writes an ErrorLog(category=upload).
- Disk write failure (mkdir/permission) rolls back the Material row and
  writes an ErrorLog(category=upload) with technical_detail.
- Successful upload writes NO ErrorLog.
"""
import io
from pathlib import Path

from app.core.database import get_db
from app.models.general_error_log import ErrorLog
from app.models.material import Material
from app.tests.conftest import auth_headers, create_course


def _test_db(client):
    return next(client.app.dependency_overrides[get_db]())


def _count_materials(db, user_id: int) -> int:
    return (
        db.query(Material)
        .filter(Material.user_id == user_id)
        .count()
    )


def test_upload_unsupported_type_writes_error_log(client, tmp_path, monkeypatch) -> None:
    """Unsupported file type raises BusinessException AND writes an error log."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")

    files = {
        "file": ("bad.exe", io.BytesIO(b"content"), "application/octet-stream"),
    }
    resp = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=files,
        headers=headers,
    )
    assert resp.status_code == 400

    logs = client.get("/api/v1/logs?category=upload", headers=headers).json()
    assert logs["total"] >= 1
    assert any("类型" in i["message"] or "type" in i["message"].lower()
               for i in logs["items"])


def test_upload_oversized_writes_error_log(client, tmp_path, monkeypatch) -> None:
    """Oversized file raises BusinessException AND writes an error log."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.MAX_UPLOAD_MB", 1)
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")

    big = b"x" * (2 * 1024 * 1024)  # 2 MB, limit is 1 MB
    files = {
        "file": ("big.txt", io.BytesIO(big), "text/plain"),
    }
    resp = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=files,
        headers=headers,
    )
    assert resp.status_code == 400

    logs = client.get("/api/v1/logs?category=upload", headers=headers).json()
    assert logs["total"] >= 1
    assert any("大小" in i["message"] or "size" in i["message"].lower()
               for i in logs["items"])


def test_upload_disk_failure_rolls_back_material_and_logs(
    client, tmp_path, monkeypatch
) -> None:
    """Disk write failure rolls back the Material row and writes an error log."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")

    # Patch Path.write_bytes to raise PermissionError simulating disk failure.
    real_write = Path.write_bytes

    def boom(self, data):
        raise PermissionError("simulated disk write failure")

    monkeypatch.setattr(Path, "write_bytes", boom)

    files = {
        "file": ("notes.txt", io.BytesIO(b"hello"), "text/plain"),
    }
    resp = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=files,
        headers=headers,
    )
    assert resp.status_code == 400

    # The Material row must have been rolled back — no orphan rows.
    db = _test_db(client)
    try:
        from app.models.user import User
        user = db.query(User).filter(User.username == "alice").first()
        assert _count_materials(db, user.id) == 0
    finally:
        db.close()

    # An error log was written.
    logs = client.get("/api/v1/logs?category=upload", headers=headers).json()
    assert logs["total"] >= 1
    last = logs["items"][0]
    assert last["level"] == "error"
    assert last["technical_detail"]


def test_upload_success_writes_no_error_log(
    client, tmp_path, monkeypatch
) -> None:
    """A successful upload writes NO error log."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")

    files = {
        "file": ("notes.txt", io.BytesIO(b"hello world"), "text/plain"),
    }
    resp = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=files,
        headers=headers,
    )
    assert resp.status_code == 201

    logs = client.get("/api/v1/logs?category=upload", headers=headers).json()
    assert logs["total"] == 0


def test_upload_disk_failure_cleans_partial_file_and_empty_dirs(
    client, tmp_path, monkeypatch
) -> None:
    """Disk write failure cleans up any partial file and empty parent dirs.

    Stability Task B: if write_bytes leaves a half-written file behind
    before raising, the exception handler must unlink it and remove the
    now-empty parent directories so no disk residue remains.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")

    # Simulate a partial write: create the file on disk, then raise.
    import os

    def boom(self, data):
        os.makedirs(str(self.parent), exist_ok=True)
        with open(str(self), "w") as fh:
            fh.write("partial-residue")
        raise PermissionError("simulated mid-write failure")

    monkeypatch.setattr(Path, "write_bytes", boom)

    files = {
        "file": ("notes.txt", io.BytesIO(b"hello"), "text/plain"),
    }
    resp = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=files,
        headers=headers,
    )
    assert resp.status_code == 400

    # No partial file should remain anywhere under UPLOAD_DIR.
    leftover = list(tmp_path.rglob("original.*"))
    assert leftover == [], f"partial file residue found: {leftover}"

    # The material row must have been rolled back.
    db = _test_db(client)
    try:
        from app.models.user import User
        user = db.query(User).filter(User.username == "alice").first()
        assert _count_materials(db, user.id) == 0
    finally:
        db.close()

    # An error log was written.
    logs = client.get("/api/v1/logs?category=upload", headers=headers).json()
    assert logs["total"] >= 1
