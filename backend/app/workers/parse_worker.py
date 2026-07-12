"""Persistent parse worker process.

The worker polls the database for queued ``ParseJob`` rows, atomically
claims one via a conditional ``UPDATE``, runs the parse with a live
heartbeat thread, and sets the final status.  Because the worker is a
standalone process (started via ``scripts/run_parse_worker.py``), an
API process restart never loses in-progress parses — the worker simply
keeps running.

Key design points
------------------
* **Atomic claim** – ``claim_next_job`` uses ``UPDATE … WHERE status='queued'
  RETURNING *`` so two workers never grab the same job.
* **Heartbeat** – a daemon thread updates ``heartbeat_at`` every
  ``heartbeat_interval`` seconds while the parse runs.  If the worker
  crashes, ``recover_stale_jobs`` (heartbeat > 600 s) resets the job to
  ``queued`` for another worker to pick up.
* **Idempotent** – ``run_once()`` processes at most one job and returns
  ``True``/``False`` so callers can loop or poll.
"""
from __future__ import annotations

import logging
import inspect
import threading
import time
from typing import Callable, Optional

from sqlalchemy.orm import Session, sessionmaker

from app.core.timezone import utc_now
from app.models.material import Material
from app.models.parse_job import ParseJob
from app.services.parse_job_service import claim_next_job

logger = logging.getLogger(__name__)

# How long (seconds) a running job's heartbeat can be stale before
# ``recover_stale_jobs`` re-queues it.
STALE_HEARTBEAT_TIMEOUT = 600


class ParseWorker:
    """Polls the DB for queued parse jobs and processes them.

    Parameters
    ----------
    session_factory
        A SQLAlchemy ``sessionmaker`` (or any callable returning a
        ``Session``).  The worker creates short-lived sessions from it
        for claim/heartbeat/finalise operations.
    parse_fn
        Callable ``(db, material, user_id) -> (status, chunk_count)``.
        Defaults to :func:`app.services.material_parser.parse_with_retry`.
    poll_interval
        Seconds to sleep between polls when no job is available.
    heartbeat_interval
        Seconds between heartbeat ``UPDATE`` ticks while a parse runs.
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        parse_fn: Callable | None = None,
        poll_interval: float = 2.0,
        heartbeat_interval: float = 5.0,
    ) -> None:
        if parse_fn is None:
            from app.services.material_parser import parse_with_retry
            parse_fn = parse_with_retry
        self.session_factory = session_factory
        self.parse_fn = parse_fn
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        # Exposed for tests to verify heartbeat ticks occurred.
        self.heartbeat_ticks: list[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run_once(self) -> bool:
        """Pick up one queued job and process it.

        Returns ``True`` if a job was processed, ``False`` if the queue
        was empty.
        """
        db = self.session_factory()
        try:
            job = self._acquire_job(db)
            if job is None:
                return False
            self._process_job(db, job)
            return True
        finally:
            db.close()

    def run_forever(self) -> None:
        """Main loop: poll for jobs, process, repeat."""
        while True:
            try:
                processed = self.run_once()
                if not processed:
                    time.sleep(self.poll_interval)
            except Exception:
                logger.exception("Worker iteration failed; continuing")
                time.sleep(self.poll_interval)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _acquire_job(self, db: Session) -> Optional[ParseJob]:
        """Atomically claim a queued job via conditional UPDATE."""
        return claim_next_job(db)

    def _process_job(self, db: Session, job: ParseJob) -> None:
        """Execute the parse, update heartbeat, set final status."""
        material = (
            db.query(Material)
            .filter(
                Material.id == job.material_id,
                Material.user_id == job.user_id,
            )
            .first()
        )
        if material is None:
            job.status = "failed"
            job.error_message = "资料不存在"
            job.finished_at = utc_now()
            job.heartbeat_at = utc_now()
            db.commit()
            return

        job.attempt += 1
        db.commit()

        # Heartbeat thread — uses its own session so it doesn't
        # interfere with the main parse session's transaction.
        stop_event = threading.Event()
        first_tick_done = threading.Event()  # signals first iteration completed
        ticks: list[float] = []
        job_id = job.id

        def _heartbeat() -> None:
            while not stop_event.is_set():
                try:
                    hb_db = self.session_factory()
                    try:
                        hb_job = hb_db.get(ParseJob, job_id)
                        if hb_job and hb_job.status == "running":
                            hb_job.heartbeat_at = utc_now()
                            hb_db.commit()
                            ticks.append(time.time())
                        else:
                            first_tick_done.set()
                            break
                    finally:
                        hb_db.close()
                except Exception:
                    logger.debug("Heartbeat tick failed", exc_info=True)
                    first_tick_done.set()
                    break
                first_tick_done.set()
                stop_event.wait(self.heartbeat_interval)

        hb_thread = threading.Thread(target=_heartbeat, daemon=True)
        hb_thread.start()
        # Wait for the heartbeat's first iteration so at least one tick
        # is recorded before the parse starts.  This prevents a race
        # where a fast parse finishes before the heartbeat thread is
        # scheduled (common on Windows / CI).
        first_tick_done.wait(timeout=2.0)

        try:
            def is_cancelled() -> bool:
                cancel_db = self.session_factory()
                try:
                    latest = cancel_db.get(ParseJob, job_id)
                    return latest is None or latest.status == "cancelled"
                finally:
                    cancel_db.close()

            if "is_cancelled" in inspect.signature(self.parse_fn).parameters:
                status, _chunk_count = self.parse_fn(
                    db, material, job.user_id, is_cancelled=is_cancelled
                )
            else:
                status, _chunk_count = self.parse_fn(db, material, job.user_id)
            db.refresh(job)
            if job.status == "cancelled" or status == "cancelled":
                return
            job.status = "succeeded" if status == "ready" else "failed"
            job.finished_at = utc_now()
            job.heartbeat_at = utc_now()
            job.error_message = (
                None
                if status == "ready"
                else (getattr(material, "last_parse_error", None) or "解析失败")
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(ParseJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.finished_at = utc_now()
                job.heartbeat_at = utc_now()
                material = (
                    db.query(Material)
                    .filter(Material.id == job.material_id)
                    .first()
                )
                if material is not None:
                    material.status = "failed"
                    material.last_parse_error = str(exc)
                    material.parse_finished_at = utc_now()
                db.commit()
        finally:
            stop_event.set()
            hb_thread.join(timeout=2.0)
            self.heartbeat_ticks = ticks
