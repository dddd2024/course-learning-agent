"""Tests for GET /api/v1/materials/{id}/overview (Phase 2 Task C)."""
from app.tests.conftest import (
    auth_headers,
    setup_course_with_material,
)


TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
).encode("utf-8")


def test_overview_owner(client, tmp_path, monkeypatch) -> None:
    """Owner gets chunk_count, page_range, keywords, warnings."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    headers = auth_headers(client, username="alice")
    course_id, material_id = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )

    resp = client.get(
        f"/api/v1/materials/{material_id}/overview", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["material_id"] == material_id
    assert body["status"] == "ready"
    assert body["chunk_count"] >= 1
    assert "page_range" in body
    assert "section_count" in body
    assert isinstance(body["keywords"], list)
    assert "warnings" in body
    assert isinstance(body["warnings"], list)


def test_overview_cross_user_404(client, tmp_path, monkeypatch) -> None:
    """User B cannot access user A's material overview."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    headers_a = auth_headers(client, username="alice")
    _, material_id = setup_course_with_material(
        client, headers_a, content=TLB_TEXT
    )

    headers_b = auth_headers(client, username="bob")
    resp = client.get(
        f"/api/v1/materials/{material_id}/overview", headers=headers_b
    )
    assert resp.status_code == 404


def test_overview_not_found(client) -> None:
    """Non-existent material_id returns 404."""
    headers = auth_headers(client, username="alice")
    resp = client.get("/api/v1/materials/99999/overview", headers=headers)
    assert resp.status_code == 404


def test_overview_unauthenticated(client) -> None:
    """Unauthenticated request returns 401."""
    resp = client.get("/api/v1/materials/1/overview")
    assert resp.status_code == 401
