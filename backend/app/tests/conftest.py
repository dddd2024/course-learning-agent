"""pytest fixtures for the course learning assistant backend.

Tests use an in-memory SQLite database so they are isolated and fast.
"""
import io
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models.base import Base


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """Return a TestClient backed by an in-memory SQLite database.

    All tables are created fresh for every test, then dropped at teardown.
    """
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )

    Base.metadata.create_all(bind=test_engine)

    def override_get_db() -> Iterator:
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def auth_headers(
    client: TestClient,
    username: str = "alice",
    password: str = "secret123",
    email: str | None = None,
) -> dict[str, str]:
    """Register a user and log in, returning ``Authorization`` headers.

    Convenience helper for protected endpoint tests: register a fresh user
    (with unique username) then log in and return the bearer header dict.
    """
    client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": password,
            "email": email or f"{username}@example.com",
        },
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_course(
    client: TestClient,
    auth_headers: dict[str, str],
    name: str = "操作系统",
) -> int:
    """Create a course for the authenticated user and return its id.

    Thin wrapper around POST /api/v1/courses so material tests can spin up
    an owned course without duplicating boilerplate.
    """
    response = client.post(
        "/api/v1/courses",
        json={"name": name},
        headers=auth_headers,
    )
    return response.json()["id"]


def upload_material(
    client: TestClient,
    auth_headers: dict[str, str],
    course_id: int,
    filename: str,
    content: bytes,
) -> int:
    """Upload a material file to a course and return its id.

    Wrapper around POST /api/v1/courses/{id}/materials that handles the
    multipart form upload so parse tests can focus on the parse flow.
    """
    files = {
        "file": (filename, io.BytesIO(content), "application/octet-stream"),
    }
    response = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=files,
        headers=auth_headers,
    )
    return response.json()["id"]


def setup_course_with_material(
    client: TestClient,
    auth_headers: dict[str, str],
    name: str = "操作系统",
    filename: str = "notes.txt",
    content: bytes | None = None,
) -> tuple[int, int]:
    """Create a course, upload a txt material, and parse it.

    Returns ``(course_id, material_id)`` so retrieval tests can spin up
    a searchable material without duplicating the create/upload/parse
    boilerplate.
    """
    if content is None:
        content = (
            "操作系统课程笔记\n"
            "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
            "页表存储虚拟页到物理页的映射关系。\n"
            "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
        ).encode("utf-8")

    course_id = create_course(client, auth_headers, name)
    material_id = upload_material(
        client, auth_headers, course_id, filename, content
    )
    parse_resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=auth_headers
    )
    assert parse_resp.status_code == 200, parse_resp.text
    return course_id, material_id
