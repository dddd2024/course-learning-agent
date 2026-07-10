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

from app.main import app
from app.tests.conftest import auth_headers, create_course, upload_material

# Diverse OS text that passes _is_low_quality_chunk filter
from app.tests._test_data import DIVERSE_OS_TEXT


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


# ---------------------------------------------------------------------------
# DELETE /api/v1/materials/{material_id}
# ---------------------------------------------------------------------------


def test_delete_material_success(client, tmp_path, monkeypatch) -> None:
    """DELETE /materials/{id} removes the material and returns 204."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client, headers, course_id, "notes.txt", b"hello world"
    )

    resp = client.delete(
        f"/api/v1/materials/{material_id}", headers=headers
    )
    assert resp.status_code == 204

    # The material no longer appears in the list.
    list_resp = client.get(
        f"/api/v1/courses/{course_id}/materials", headers=headers
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert all(m["id"] != material_id for m in items)


def test_delete_other_user_material_returns_404(
    client, tmp_path, monkeypatch
) -> None:
    """Deleting another user's material returns 404 (no existence leak)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers_a = auth_headers(client, username="alice")
    course_id = create_course(client, headers_a, "操作系统")
    material_id = upload_material(
        client, headers_a, course_id, "notes.txt", b"content"
    )

    headers_b = auth_headers(client, username="bob")
    resp = client.delete(
        f"/api/v1/materials/{material_id}", headers=headers_b
    )
    assert resp.status_code == 404

    # The material still exists for alice.
    list_resp = client.get(
        f"/api/v1/courses/{course_id}/materials", headers=headers_a
    )
    assert any(m["id"] == material_id for m in list_resp.json()["items"])


def test_delete_material_clears_chunks(client, tmp_path, monkeypatch) -> None:
    """Deleting a material also removes all of its chunks."""
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
        (DIVERSE_OS_TEXT * 2).encode("utf-8"),
    )
    # Parse so chunks exist (background task, returns processing).
    parse_resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert parse_resp.status_code == 200
    # Background task: endpoint returns processing immediately, chunk_count=0.
    # Verify the background task completed and chunks exist.
    chunks_before = client.get(
        f"/api/v1/materials/{material_id}/chunks",
        params={"page": 1, "page_size": 100},
        headers=headers,
    )
    assert chunks_before.status_code == 200
    assert len(chunks_before.json()["items"]) > 0

    del_resp = client.delete(
        f"/api/v1/materials/{material_id}", headers=headers
    )
    assert del_resp.status_code == 204

    # Chunks for this material are gone (404 because the material is gone).
    chunks_resp = client.get(
        f"/api/v1/materials/{material_id}/chunks", headers=headers
    )
    assert chunks_resp.status_code == 404


def test_delete_material_missing_disk_file_still_succeeds(
    client, tmp_path, monkeypatch
) -> None:
    """If the disk file is already gone, DELETE still returns 204."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client, headers, course_id, "notes.txt", b"content"
    )

    # Read the stored relative path from the API (no direct DB access) and
    # remove the file from disk before deleting the record.
    list_resp = client.get(
        f"/api/v1/courses/{course_id}/materials", headers=headers
    )
    mat = next(m for m in list_resp.json()["items"] if m["id"] == material_id)
    disk_path = tmp_path / mat["file_path"]
    disk_path.unlink(missing_ok=True)

    resp = client.delete(
        f"/api/v1/materials/{material_id}", headers=headers
    )
    assert resp.status_code == 204


def test_delete_processing_material_returns_400(
    client, tmp_path, monkeypatch
) -> None:
    """A material in 'processing' status cannot be deleted (returns 400)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client, headers, course_id, "notes.txt", b"content"
    )

    # Force the material into 'processing' status using the same test DB
    # session the client fixture wired into get_db (avoid the production
    # SessionLocal, which points at a different database).
    from app.core.database import get_db
    from app.models.material import Material

    db = next(app.dependency_overrides[get_db]())
    try:
        mat = db.query(Material).filter(Material.id == material_id).first()
        mat.status = "processing"
        db.commit()
    finally:
        db.close()

    resp = client.delete(
        f"/api/v1/materials/{material_id}", headers=headers
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "处理" in body["message"] or "processing" in body["message"].lower()
