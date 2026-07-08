"""Timezone-aware UTC helpers.

The project used to store ``datetime.utcnow()`` (naive UTC) and format it
directly on the frontend with ``toLocaleString()``, which produced an 8-hour
skew on Chinese-timezone clients. These helpers centralise timezone-aware
UTC datetimes so every model and service uses the same source of truth.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Use this instead of ``datetime.utcnow()`` (which returns a naive
    datetime) so SQLAlchemy ``DateTime(timezone=True)`` columns store a
    proper timestamp and the API serializes it as an ISO 8601 string with
    an explicit offset.
    """
    return datetime.now(timezone.utc)
