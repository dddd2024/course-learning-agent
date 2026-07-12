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


@pytest.fixture(autouse=True)
def _fast_parse_retries(monkeypatch):
    """Skip time.sleep in material_parser retries to keep tests fast.

    The parse retry service uses real time.sleep(2)/sleep(5) delays
    between retries. In tests these delays are pointless (the parse_fn
    is always a mock or a fast in-memory operation) so we patch
    ``time.sleep`` in the material_parser module to a no-op.
    """
    monkeypatch.setattr("app.services.material_parser.time.sleep", lambda _: None)


@pytest.fixture(autouse=True)
def _allow_private_llm_endpoints_in_tests(monkeypatch):
    """Allow private/localhost LLM endpoints in tests by default.

    SEC-V3-01 SSRF protection blocks localhost/private addresses by
    default (``ALLOW_PRIVATE_LLM_ENDPOINTS=False``). Many existing tests
    use localhost URLs or public URLs that resolve to private IPs in the
    test environment. This fixture sets ``ALLOW_PRIVATE_LLM_ENDPOINTS=True``
    for all tests so those tests pass.

    Tests that specifically verify SSRF rejection (e.g.
    ``test_v3_ssrf.py``) override this by setting
    ``ALLOW_PRIVATE_LLM_ENDPOINTS=False`` in their own autouse fixture,
    which runs after this one and takes precedence.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "ALLOW_PRIVATE_LLM_ENDPOINTS", True)


@pytest.fixture()
def client(monkeypatch) -> Iterator[TestClient]:
    """Return a TestClient backed by an in-memory SQLite database.

    All tables are created fresh for every test, then dropped at teardown.
    ``SessionLocal`` is also patched so background tasks (which create
    their own sessions outside the request lifecycle) hit the same
    in-memory test database instead of the production file DB.
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

    # Patch SessionLocal so background tasks using SessionLocal() land on
    # the in-memory test DB (stability Task A: session isolation).
    monkeypatch.setattr("app.core.database.SessionLocal", TestSessionLocal)

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


@pytest.fixture()
def db_session():
    """SQLAlchemy session for direct model/service tests (no HTTP layer).

    Separate from the ``client`` fixture: creates a fresh in-memory SQLite
    database, yields a session, then drops all tables. Used by model and
    service tests that need ORM access without going through the API.
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
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def sample_user(db_session):
    """A User row for model/service tests."""
    from app.models import User

    user = User(
        username="alice",
        email="alice@test.com",
        password_hash="x",
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def sample_course(db_session, sample_user):
    """A Course row owned by ``sample_user``."""
    from app.models import Course

    course = Course(name="操作系统", user_id=sample_user.id)
    db_session.add(course)
    db_session.commit()
    return course


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

    # V6-50: the API no longer runs the parse in-process.  Run any
    # queued jobs synchronously so subsequent test assertions see
    # parsed chunks / ready status.
    run_pending_parse_jobs(client)

    return course_id, material_id


def run_pending_parse_jobs(client: TestClient) -> None:
    """Process all queued ParseJobs synchronously (for tests).

    V6-50: ``POST /materials/{id}/parse`` only creates a queued job; a
    persistent ``ParseWorker`` does the actual parsing.  In tests there
    is no worker process, so this helper runs ``run_job`` for every
    queued job using the patched ``SessionLocal`` (which points at the
    in-memory test DB).

    ``parse_fn`` is intentionally NOT passed so that ``run_job`` uses
    its module-level ``parse_with_retry`` — this allows tests to
    monkeypatch ``app.services.parse_job_service.parse_with_retry``
    and have the patch take effect.
    """
    from app.core.database import SessionLocal
    from app.models.parse_job import ParseJob
    from app.services.parse_job_service import run_job

    db = SessionLocal()
    try:
        jobs = (
            db.query(ParseJob)
            .filter(ParseJob.status == "queued")
            .order_by(ParseJob.created_at)
            .all()
        )
        job_ids = [j.id for j in jobs]
    finally:
        db.close()

    for jid in job_ids:
        run_job(jid)
