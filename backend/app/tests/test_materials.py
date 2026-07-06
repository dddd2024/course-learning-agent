"""Tests for the materials upload and storage module.

Strict TDD: these tests are written first and fail until the materials
router, schemas, and model are implemented.

Covers:
- POST /api/v1/courses/{id}/materials (upload, .txt)
- GET  /api/v1/courses/{id}/materials (list)
- File type whitelist validation (.exe rejected -> 400)
- Per-user data isolation (404 on cross-user access)
- Auth required (401 without token)
"""
import io

from app.tests.conftest import auth_headers, create_course


def test_upload_material_success(client, tmp_path, monkeypatch) -> None:
    """POST /api/v1/courses/{id}/materials returns 201 with metadata."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")

    files = {
        "file": ("notes.txt", io.BytesIO(b"Hello, world!"), "text/plain"),
    }
    response = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=files,
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["filename"] == "notes.txt"
    assert body["file_type"] == "txt"
    assert body["status"] == "uploaded"


def test_upload_invalid_file_type(client, tmp_path, monkeypatch) -> None:
    """Uploading a .exe file returns 400 (invalid file type)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers = auth_headers(client, username="bob")
    course_id = create_course(client, headers, "操作系统")

    files = {
        "file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream"),
    }
    response = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=files,
        headers=headers,
    )

    assert response.status_code == 400


def test_upload_to_other_user_course(client, tmp_path, monkeypatch) -> None:
    """User B cannot upload to user A's course (returns 404)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers_a = auth_headers(client, username="alice")
    course_id = create_course(client, headers_a, "操作系统")

    headers_b = auth_headers(client, username="bob")
    files = {
        "file": ("notes.txt", io.BytesIO(b"Hi"), "text/plain"),
    }
    response = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=files,
        headers=headers_b,
    )

    assert response.status_code == 404


def test_list_materials(client, tmp_path, monkeypatch) -> None:
    """GET /api/v1/courses/{id}/materials returns the uploaded materials."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers = auth_headers(client, username="carol")
    course_id = create_course(client, headers, "操作系统")

    for name in ("notes.txt", "summary.md"):
        files = {"file": (name, io.BytesIO(b"content"), "text/plain")}
        client.post(
            f"/api/v1/courses/{course_id}/materials",
            files=files,
            headers=headers,
        )

    response = client.get(
        f"/api/v1/courses/{course_id}/materials", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    items = body["items"] if isinstance(body, dict) else body
    assert len(items) == 2


def test_list_materials_isolation(client, tmp_path, monkeypatch) -> None:
    """User B cannot see user A's materials (course invisible -> 404)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers_a = auth_headers(client, username="alice")
    course_id = create_course(client, headers_a, "操作系统")
    files = {"file": ("notes.txt", io.BytesIO(b"content"), "text/plain")}
    client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=files,
        headers=headers_a,
    )

    headers_b = auth_headers(client, username="bob")
    response = client.get(
        f"/api/v1/courses/{course_id}/materials", headers=headers_b
    )

    assert response.status_code == 404


def test_upload_without_auth(client) -> None:
    """POST without an Authorization header returns 401."""
    files = {"file": ("notes.txt", io.BytesIO(b"content"), "text/plain")}
    response = client.post(
        "/api/v1/courses/1/materials",
        files=files,
    )

    assert response.status_code == 401
