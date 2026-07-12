"""Tests for background parse DB session isolation (stability Task A).

The background parse task must:
1. Create its own database session via ``SessionLocal`` (not reuse the
   request-level session).
2. Recover from exceptions so a material never gets stuck in
   ``processing`` — it should flip to ``failed`` and write a
   ``category=parse`` error log.
"""
import app.core.database as db_module
from app.tests.conftest import auth_headers, create_course, upload_material, run_pending_parse_jobs


def test_background_parse_recovers_from_exception(
    client, tmp_path, monkeypatch
) -> None:
    """parse_with_retry raising -> material flips to failed + error log."""
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
        ("操作系统管理硬件资源。" * 30).encode("utf-8"),
    )

    def boom(*args, **kwargs):
        raise RuntimeError("simulated parse crash")

    # V6-50: parse_with_retry is no longer imported in parse.py; patch
    # the reference in parse_job_service (which run_job uses).
    monkeypatch.setattr("app.services.parse_job_service.parse_with_retry", boom)

    resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing"
    run_pending_parse_jobs(client)

    # Background task runs synchronously in TestClient. The exception
    # handler must flip the material to failed (not stuck processing).
    mat_resp = client.get(
        f"/api/v1/courses/{course_id}/materials", headers=headers
    )
    mat = next(m for m in mat_resp.json()["items"] if m["id"] == material_id)
    assert mat["status"] == "failed"
    assert mat["error_message"] is not None

    # A parse error log must exist.
    logs_resp = client.get(
        "/api/v1/logs", params={"category": "parse"}, headers=headers
    )
    assert logs_resp.status_code == 200
    logs_body = logs_resp.json()
    logs = logs_body["items"] if isinstance(logs_body, dict) else logs_body
    assert any("解析" in (lg.get("title") or "") for lg in logs)


def test_background_parse_uses_independent_session(
    client, tmp_path, monkeypatch
) -> None:
    """Background task creates its own SessionLocal, not the request db."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    created_count = {"n": 0}
    real_factory = db_module.SessionLocal

    def tracking_factory():
        created_count["n"] += 1
        return real_factory()

    monkeypatch.setattr(db_module, "SessionLocal", tracking_factory)

    headers = auth_headers(client, username="bob")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client,
        headers,
        course_id,
        "notes.txt",
        ("进程是程序运行的过程。" * 30).encode("utf-8"),
    )

    resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert resp.status_code == 200

    # V6-50: the API no longer runs parse in-process; run pending jobs
    # so the material reaches ready state.
    run_pending_parse_jobs(client)

    # run_job creates its own session via SessionLocal (proving it does
    # not reuse the request-level db).
    assert created_count["n"] >= 1

    # And the parse should have succeeded (material ready).
    mat_resp = client.get(
        f"/api/v1/courses/{course_id}/materials", headers=headers
    )
    mat = next(m for m in mat_resp.json()["items"] if m["id"] == material_id)
    assert mat["status"] == "ready"
