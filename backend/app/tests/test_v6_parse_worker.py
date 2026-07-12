"""Tests for the persistent parse worker (V6-50).

The API must only *create* a queued ParseJob and return immediately; a
long-lived ParseWorker process polls the DB, atomically claims queued
jobs, runs the parse with a heartbeat, and sets the final status. These
tests cover the worker contract and the API/job-service changes.
"""
from __future__ import annotations

import io
import threading
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.timezone import utc_now
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.parse_job import ParseJob
from app.services.parse_job_service import (
    claim_next_job,
    recover_stale_jobs,
)
from app.tests.conftest import auth_headers, create_course, upload_material
from app.workers.parse_worker import ParseWorker


# ---------------------------------------------------------------------------
# Module-level db_session override.
#
# The conftest db_session uses an in-memory StaticPool SQLite (a single
# shared connection). A ParseWorker runs the parse in a worker thread with
# its own session and ticks the heartbeat from the main thread, so it needs
# *separate* connections that coordinate via SQLite locking. We therefore use
# a file-based SQLite (WAL + busy_timeout) for these tests and expose the
# session factory on the session (``db_session.factory``) so a ParseWorker
# can be constructed against the very same database.
# ---------------------------------------------------------------------------
@pytest.fixture()
def db_session(tmp_path):
    db_file = tmp_path / "worker_test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    from app.models.base import Base

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = factory()
    # Expose the factory so tests can build a ParseWorker sharing this DB.
    session.factory = factory
    try:
        yield session
    finally:
        session.close()
        # Disable FK enforcement before dropping so teardown doesn't fail
        # on orphaned rows left by the heartbeat thread's sessions.
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            Base.metadata.drop_all(bind=conn)
        engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_material(db, user, course, *, filename="notes.txt", status="uploaded"):
    mat = Material(
        user_id=user.id,
        course_id=course.id,
        filename=filename,
        file_type="txt",
        file_path="x",
        status=status,
    )
    db.add(mat)
    db.commit()
    return mat


def _make_job(db, material, user, *, status="queued", heartbeat_at=None, attempt=0):
    job = ParseJob(
        material_id=material.id,
        user_id=user.id,
        status=status,
        heartbeat_at=heartbeat_at,
        attempt=attempt,
    )
    db.add(job)
    db.commit()
    return job


def _fake_parse(status="ready", chunk_count=1, sleep=0.0, exc=None, recorder=None):
    """Build a parse_fn(db, material, user_id) for worker tests.

    Uses ``threading.Event().wait()`` instead of ``time.sleep`` because
    the autouse ``_fast_parse_retries`` conftest fixture monkeypatches
    ``time.sleep`` globally (it patches the ``time`` module singleton).
    ``Event.wait`` is unaffected by that patch.
    """
    _block = threading.Event()

    def _fn(db, material, user_id):
        if recorder is not None:
            recorder["start"] = time.time()
        if sleep:
            _block.wait(sleep)
        if recorder is not None:
            recorder["end"] = time.time()
        if exc is not None:
            raise exc
        return status, chunk_count

    return _fn


def _refresh(db, job):
    """Re-read the job from the DB (the worker mutates it on another conn)."""
    db.expire_all()
    return db.get(ParseJob, job.id)


# ---------------------------------------------------------------------------
# 1. API only creates a job; it does NOT run the parse in-process.
# ---------------------------------------------------------------------------
def test_api_creates_job_without_running_parse(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client, headers, course_id, "notes.txt", b"hello world"
    )

    resp = client.post(f"/api/v1/materials/{material_id}/parse", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing"

    db = next(client.app.dependency_overrides[get_db]())
    try:
        job = (
            db.query(ParseJob)
            .filter(ParseJob.material_id == material_id)
            .first()
        )
        assert job is not None
        # The job is queued for the worker; the parse has NOT run yet.
        assert job.status == "queued"
        assert job.started_at is None

        chunks = (
            db.query(MaterialChunk)
            .filter(MaterialChunk.material_id == material_id)
            .count()
        )
        assert chunks == 0

        mat = db.query(Material).filter(Material.id == material_id).first()
        assert mat.status == "processing"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2. Worker picks up a queued job.
# ---------------------------------------------------------------------------
def test_worker_picks_up_queued_job(db_session, sample_user, sample_course):
    mat = _make_material(db_session, sample_user, sample_course)
    job = _make_job(db_session, mat, sample_user)

    worker = ParseWorker(
        session_factory=db_session.factory,
        parse_fn=_fake_parse(status="ready"),
    )
    assert worker.run_once() is True

    job = _refresh(db_session, job)
    assert job.status == "succeeded"


# ---------------------------------------------------------------------------
# 3. Heartbeat is updated during parsing.
# ---------------------------------------------------------------------------
def test_worker_heartbeat_during_parse(db_session, sample_user, sample_course):
    mat = _make_material(db_session, sample_user, sample_course)
    job = _make_job(db_session, mat, sample_user)
    before = utc_now().replace(tzinfo=None)  # SQLite stores naive datetimes

    recorder = {}
    worker = ParseWorker(
        session_factory=db_session.factory,
        parse_fn=_fake_parse(sleep=0.2, recorder=recorder),
        heartbeat_interval=0.04,
    )
    assert worker.run_once() is True

    ticks = worker.heartbeat_ticks
    assert len(ticks) >= 1
    # At least one heartbeat tick occurred during the parse window.
    assert any(recorder["start"] <= t <= recorder["end"] for t in ticks)

    job = _refresh(db_session, job)
    assert job.heartbeat_at is not None
    assert job.heartbeat_at >= before


# ---------------------------------------------------------------------------
# 4. Worker sets succeeded on success.
# ---------------------------------------------------------------------------
def test_worker_sets_succeeded_on_success(db_session, sample_user, sample_course):
    mat = _make_material(db_session, sample_user, sample_course)
    job = _make_job(db_session, mat, sample_user)

    worker = ParseWorker(
        session_factory=db_session.factory,
        parse_fn=_fake_parse(status="ready", chunk_count=3),
    )
    assert worker.run_once() is True

    job = _refresh(db_session, job)
    assert job.status == "succeeded"
    assert job.finished_at is not None
    assert job.error_message is None


# ---------------------------------------------------------------------------
# 5. Worker sets failed on error.
# ---------------------------------------------------------------------------
def test_worker_sets_failed_on_error(db_session, sample_user, sample_course):
    mat = _make_material(db_session, sample_user, sample_course)
    job = _make_job(db_session, mat, sample_user)

    worker = ParseWorker(
        session_factory=db_session.factory,
        parse_fn=_fake_parse(exc=RuntimeError("boom: parse crashed")),
    )
    assert worker.run_once() is True

    job = _refresh(db_session, job)
    assert job.status == "failed"
    assert job.error_message is not None
    assert "boom" in job.error_message


# ---------------------------------------------------------------------------
# 6. Two workers can't claim the same job.
# ---------------------------------------------------------------------------
def test_worker_no_duplicate_claim(db_session, sample_user, sample_course):
    mat = _make_material(db_session, sample_user, sample_course)
    job = _make_job(db_session, mat, sample_user)

    worker = ParseWorker(session_factory=db_session.factory)

    # First worker claims the only queued job.
    db1 = db_session.factory()
    try:
        claimed1 = worker._acquire_job(db1)
        assert claimed1 is not None
        assert claimed1.id == job.id
        assert claimed1.status == "running"
    finally:
        db1.close()

    # A second worker finds no queued job left to claim.
    db2 = db_session.factory()
    try:
        claimed2 = worker._acquire_job(db2)
        assert claimed2 is None
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 7. Stale running job is recovered to queued.
# ---------------------------------------------------------------------------
def test_recover_stale_running_job(db_session, sample_user, sample_course):
    mat = _make_material(db_session, sample_user, sample_course)
    job = _make_job(
        db_session,
        mat,
        sample_user,
        status="running",
        heartbeat_at=utc_now() - timedelta(seconds=700),
        attempt=0,
    )

    assert recover_stale_jobs(db_session) == 1

    job = _refresh(db_session, job)
    assert job.status == "queued"


# ---------------------------------------------------------------------------
# 8. Multiple queued jobs are processed in order.
# ---------------------------------------------------------------------------
def test_worker_processes_multiple_jobs(db_session, sample_user, sample_course):
    mat1 = _make_material(db_session, sample_user, sample_course)
    job1 = _make_job(db_session, mat1, sample_user)
    mat2 = _make_material(db_session, sample_user, sample_course)
    job2 = _make_job(db_session, mat2, sample_user)
    assert job1.created_at <= job2.created_at

    worker = ParseWorker(
        session_factory=db_session.factory,
        parse_fn=_fake_parse(status="ready"),
    )

    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is False  # no more queued jobs

    job1 = _refresh(db_session, job1)
    job2 = _refresh(db_session, job2)
    assert job1.status == "succeeded"
    assert job2.status == "succeeded"
    # Processed in created_at order: job1 finished no later than job2.
    assert job1.finished_at <= job2.finished_at


# ---------------------------------------------------------------------------
# 9. Worker is idle when there are no jobs.
# ---------------------------------------------------------------------------
def test_worker_idle_when_no_jobs(db_session, sample_user, sample_course):
    _make_material(db_session, sample_user, sample_course)  # material, no job
    worker = ParseWorker(session_factory=db_session.factory)
    assert worker.run_once() is False


# ---------------------------------------------------------------------------
# 10. A cancelled job is not picked up.
# ---------------------------------------------------------------------------
def test_cancelled_job_not_processed(db_session, sample_user, sample_course):
    mat = _make_material(db_session, sample_user, sample_course)
    job = _make_job(db_session, mat, sample_user, status="cancelled")

    worker = ParseWorker(
        session_factory=db_session.factory,
        parse_fn=_fake_parse(exc=AssertionError("should not run")),
    )
    assert worker.run_once() is False

    job = _refresh(db_session, job)
    assert job.status == "cancelled"
