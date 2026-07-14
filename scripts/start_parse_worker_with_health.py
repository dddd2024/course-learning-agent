#!/usr/bin/env python
"""Start the parse worker with a minimal HTTP health-check endpoint.

Used by ``playwright.config.ts`` as a ``webServer`` entry so Playwright
can detect when the worker is ready.  The worker polls the DB for queued
``ParseJob`` rows; the health server listens on port 8001 and always
returns 200 OK.

Usage::

    python scripts/start_parse_worker_with_health.py
"""
from __future__ import annotations

import http.server
import json
import logging
import os
import signal
import sys
import threading

# Ensure the backend package is importable when running from the
# project root.
sys.path.insert(0, "backend")

from app.core.database import SessionLocal  # noqa: E402
from app.core.config import e2e_runtime_info  # noqa: E402
from app.workers.parse_worker import ParseWorker  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("parse_worker_health")


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    """Return the worker's E2E identity as well as liveness."""

    def do_GET(self):  # noqa: N802 – http.server convention
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "e2e": e2e_runtime_info()}).encode("utf-8"))

    def do_POST(self):  # noqa: N802 – http.server convention
        if self.path != "/shutdown" or not os.getenv("E2E_MODE"):
            self.send_error(404)
            return
        self.send_response(202)
        self.end_headers()
        threading.Timer(0.2, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()

    def log_message(self, *args):  # noqa: D401 – silence access log
        pass


def main() -> None:
    health_port = int(os.getenv("PARSE_WORKER_HEALTH_PORT", "8001"))
    # Start health-check HTTP server on a configurable local port.
    health_server = http.server.HTTPServer(
        ("127.0.0.1", health_port), _HealthHandler
    )
    threading.Thread(
        target=health_server.serve_forever, daemon=True
    ).start()
    logger.info("Health check listening on http://127.0.0.1:%s", health_port)

    # Start the parse worker.
    worker = ParseWorker(
        session_factory=SessionLocal,
        poll_interval=2.0,
        heartbeat_interval=5.0,
    )

    def _shutdown(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        health_server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Parse worker started - polling for queued jobs...")
    worker.run_forever()


if __name__ == "__main__":
    main()
