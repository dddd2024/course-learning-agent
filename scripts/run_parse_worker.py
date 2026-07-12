#!/usr/bin/env python
"""CLI entry point for the persistent parse worker.

Usage::

    python scripts/run_parse_worker.py

The worker connects to the same database as the API (configured via
``DATABASE_URL`` in ``app.core.config.settings``) and polls for queued
``ParseJob`` rows.  It runs indefinitely until interrupted (Ctrl-C).

A single instance is sufficient for development; for production you may
run multiple instances — the ``claim_next_job`` conditional UPDATE
prevents duplicate processing.
"""
import logging
import signal
import sys

# Ensure the backend package is importable when running from the
# project root.
sys.path.insert(0, "backend")

from app.core.database import SessionLocal  # noqa: E402
from app.workers.parse_worker import ParseWorker  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("parse_worker")


def main() -> None:
    worker = ParseWorker(
        session_factory=SessionLocal,
        poll_interval=2.0,
        heartbeat_interval=5.0,
    )

    def _shutdown(signum, frame):
        logger.info("Received signal %s, shutting down…", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Parse worker started — polling for queued jobs…")
    worker.run_forever()


if __name__ == "__main__":
    main()
