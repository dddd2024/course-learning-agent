"""Tests for the general ErrorLog center (parse/upload/agent/search/system).

Unlike the existing AgentErrorLog (Phase 2 Task E, agent-only), this table
records failures across all categories so the frontend "日志中心" can show
one diagnostic surface. Success flows do NOT write here — only failures and
warnings. All queries are scoped by current_user.id.
"""
from app.core.database import get_db
from app.models.general_error_log import ErrorLog
from app.models.user import User
from app.tests.conftest import auth_headers, create_course


def _test_db(client):
    """Return the test session bound to the client's in-memory DB."""
    return next(client.app.dependency_overrides[get_db]())


def _seed_log(db, user_id, **kwargs) -> ErrorLog:
    """Insert one ErrorLog row for ``user_id`` with sensible defaults."""
    defaults = dict(
        category="parse",
        level="error",
        status="open",
        title="资料解析失败",
        message="PDF 文本提取为空",
        retry_count=0,
    )
    defaults.update(kwargs)
    log = ErrorLog(user_id=user_id, **defaults)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# ---------------------------------------------------------------------------
# GET /logs
# ---------------------------------------------------------------------------

def test_list_logs_empty(client) -> None:
    """A new user sees an empty log center."""
    headers = auth_headers(client, username="alice")
    resp = client.get("/api/v1/logs", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_list_logs_unauthenticated(client) -> None:
    """Unauthenticated request returns 401."""
    resp = client.get("/api/v1/logs")
    assert resp.status_code == 401


def test_list_logs_user_isolation(client) -> None:
    """User B cannot see user A's error logs."""
    headers_a = auth_headers(client, username="alice")
    db = _test_db(client)
    try:
        user = db.query(User).filter(User.username == "alice").first()
        _seed_log(db, user.id, message="alice's failure")
    finally:
        db.close()

    # Alice sees 1
    resp_a = client.get("/api/v1/logs", headers=headers_a)
    assert resp_a.status_code == 200
    assert resp_a.json()["total"] == 1

    # Bob sees 0
    headers_b = auth_headers(client, username="bob")
    resp_b = client.get("/api/v1/logs", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["total"] == 0


def test_list_logs_filter_by_category(client) -> None:
    """?category=parse only returns parse logs."""
    headers = auth_headers(client, username="alice")
    db = _test_db(client)
    try:
        user = db.query(User).filter(User.username == "alice").first()
        _seed_log(db, user.id, category="parse", title="解析失败")
        _seed_log(db, user.id, category="upload", title="上传失败")
    finally:
        db.close()

    resp = client.get("/api/v1/logs?category=parse", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["category"] == "parse"


def test_list_logs_filter_by_level_and_status(client) -> None:
    """?level=error&status=open filters correctly."""
    headers = auth_headers(client, username="alice")
    db = _test_db(client)
    try:
        user = db.query(User).filter(User.username == "alice").first()
        _seed_log(db, user.id, level="error", status="open")
        _seed_log(db, user.id, level="warning", status="open")
        _seed_log(db, user.id, level="error", status="resolved")
    finally:
        db.close()

    resp = client.get(
        "/api/v1/logs?level=error&status=open", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["level"] == "error"
    assert item["status"] == "open"


# ---------------------------------------------------------------------------
# GET /logs/{id}
# ---------------------------------------------------------------------------

def test_get_log_detail(client) -> None:
    """GET /logs/{id} returns the full log including technical_detail."""
    headers = auth_headers(client, username="alice")
    db = _test_db(client)
    try:
        user = db.query(User).filter(User.username == "alice").first()
        log = _seed_log(
            db,
            user.id,
            technical_detail="pdfplumber.PDFSyntaxError: EOF not found",
            retry_count=3,
            max_retries=3,
        )
        log_id = log.id
    finally:
        db.close()

    resp = client.get(f"/api/v1/logs/{log_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == log_id
    assert body["technical_detail"].startswith("pdfplumber")
    assert body["retry_count"] == 3
    assert body["max_retries"] == 3


def test_get_log_cross_user_returns_404(client) -> None:
    """User B cannot read user A's log detail (404, no existence leak)."""
    headers_a = auth_headers(client, username="alice")
    db = _test_db(client)
    try:
        user = db.query(User).filter(User.username == "alice").first()
        log = _seed_log(db, user.id)
        log_id = log.id
    finally:
        db.close()

    headers_b = auth_headers(client, username="bob")
    resp = client.get(f"/api/v1/logs/{log_id}", headers=headers_b)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /logs/{id}/resolve
# ---------------------------------------------------------------------------

def test_resolve_log(client) -> None:
    """POST /logs/{id}/resolve marks the log as resolved."""
    headers = auth_headers(client, username="alice")
    db = _test_db(client)
    try:
        user = db.query(User).filter(User.username == "alice").first()
        log = _seed_log(db, user.id, status="open")
        log_id = log.id
    finally:
        db.close()

    resp = client.post(f"/api/v1/logs/{log_id}/resolve", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"

    # Persisted
    resp2 = client.get(f"/api/v1/logs/{log_id}", headers=headers)
    assert resp2.json()["status"] == "resolved"


def test_resolve_log_cross_user_returns_404(client) -> None:
    """User B cannot resolve user A's log (404)."""
    headers_a = auth_headers(client, username="alice")
    db = _test_db(client)
    try:
        user = db.query(User).filter(User.username == "alice").first()
        log = _seed_log(db, user.id)
        log_id = log.id
    finally:
        db.close()

    headers_b = auth_headers(client, username="bob")
    resp = client.post(f"/api/v1/logs/{log_id}/resolve", headers=headers_b)
    assert resp.status_code == 404
