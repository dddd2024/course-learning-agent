"""Tests for the course module CRUD endpoints.

Strict TDD: these tests are written first and fail until the courses
router, schemas, and model are implemented.

Covers:
- POST /api/v1/courses        (create)
- GET  /api/v1/courses        (list, paginated, keyword search)
- GET  /api/v1/courses/{id}   (detail)
- PUT  /api/v1/courses/{id}   (update)
- DELETE /api/v1/courses/{id} (delete)
- Per-user data isolation
- Auth required (401 without token)
"""
from app.tests.conftest import auth_headers


COURSE_PAYLOAD = {
    "name": "操作系统",
    "teacher": "张老师",
    "semester": "2025-2026-2",
    "description": "进程管理、内存管理、文件系统与 I/O",
}


def test_create_course(client) -> None:
    """POST /api/v1/courses returns 201 with id and name."""
    headers = auth_headers(client, username="alice")

    response = client.post("/api/v1/courses", json=COURSE_PAYLOAD, headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["name"] == "操作系统"
    assert body["teacher"] == "张老师"
    assert body["semester"] == "2025-2026-2"


def test_list_courses(client) -> None:
    """GET /api/v1/courses returns the user's courses."""
    headers = auth_headers(client, username="bob")

    client.post(
        "/api/v1/courses",
        json={**COURSE_PAYLOAD, "name": "操作系统"},
        headers=headers,
    )
    client.post(
        "/api/v1/courses",
        json={**COURSE_PAYLOAD, "name": "计算机网络"},
        headers=headers,
    )

    response = client.get("/api/v1/courses", headers=headers)

    assert response.status_code == 200
    body = response.json()
    # 支持纯列表或分页结构
    items = body["items"] if isinstance(body, dict) else body
    assert len(items) == 2


def test_get_course_by_id(client) -> None:
    """GET /api/v1/courses/{id} returns the course detail."""
    headers = auth_headers(client, username="carol")

    create_resp = client.post("/api/v1/courses", json=COURSE_PAYLOAD, headers=headers)
    course_id = create_resp.json()["id"]

    response = client.get(f"/api/v1/courses/{course_id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == course_id
    assert body["name"] == "操作系统"


def test_update_course(client) -> None:
    """PUT /api/v1/courses/{id} updates the course; GET reflects the change."""
    headers = auth_headers(client, username="dave")

    create_resp = client.post("/api/v1/courses", json=COURSE_PAYLOAD, headers=headers)
    course_id = create_resp.json()["id"]

    update_resp = client.put(
        f"/api/v1/courses/{course_id}",
        json={"teacher": "李老师"},
        headers=headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["teacher"] == "李老师"

    get_resp = client.get(f"/api/v1/courses/{course_id}", headers=headers)
    assert get_resp.json()["teacher"] == "李老师"


def test_delete_course(client) -> None:
    """DELETE /api/v1/courses/{id} removes it; subsequent GET returns 404."""
    headers = auth_headers(client, username="eve")

    create_resp = client.post("/api/v1/courses", json=COURSE_PAYLOAD, headers=headers)
    course_id = create_resp.json()["id"]

    del_resp = client.delete(f"/api/v1/courses/{course_id}", headers=headers)
    assert del_resp.status_code in (200, 204)

    get_resp = client.get(f"/api/v1/courses/{course_id}", headers=headers)
    assert get_resp.status_code == 404


def test_course_isolation(client) -> None:
    """User B cannot read user A's course (returns 404, not 403)."""
    headers_a = auth_headers(client, username="alice")
    create_resp = client.post("/api/v1/courses", json=COURSE_PAYLOAD, headers=headers_a)
    course_id = create_resp.json()["id"]

    headers_b = auth_headers(client, username="bob")

    get_resp = client.get(f"/api/v1/courses/{course_id}", headers=headers_b)
    assert get_resp.status_code == 404

    update_resp = client.put(
        f"/api/v1/courses/{course_id}",
        json={"teacher": "黑客"},
        headers=headers_b,
    )
    assert update_resp.status_code == 404

    delete_resp = client.delete(f"/api/v1/courses/{course_id}", headers=headers_b)
    assert delete_resp.status_code == 404


def test_list_courses_pagination(client) -> None:
    """GET /api/v1/courses?page=1&page_size=10 returns a paginated structure."""
    headers = auth_headers(client, username="frank")

    for i in range(3):
        client.post(
            "/api/v1/courses",
            json={**COURSE_PAYLOAD, "name": f"课程{i}"},
            headers=headers,
        )

    response = client.get(
        "/api/v1/courses?page=1&page_size=10", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["total"] == 3
    assert len(body["items"]) == 3


def test_unauthorized_access(client) -> None:
    """GET /api/v1/courses without a token returns 401."""
    response = client.get("/api/v1/courses")
    assert response.status_code == 401
