"""Deterministic, persisted progress maintenance for weak points."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models.quiz import WeakPoint


_DECAY_GRACE_DAYS = 21
_DECAY_PERIOD_DAYS = 14
_DECAY_POINTS = 5


def apply_mastery_decay(weak_point: WeakPoint, now: datetime | None = None) -> bool:
    """Apply bounded forgetting only after a meaningful practice gap.

    The timestamp is stored separately from ``last_practiced_at`` so reading a
    weak-point list never masquerades as a study event and repeated reads do
    not repeatedly subtract score for the same elapsed time.
    """
    now = now or datetime.now()
    last_practiced = weak_point.last_practiced_at
    if last_practiced is None:
        return False
    eligible_at = last_practiced + timedelta(days=_DECAY_GRACE_DAYS)
    if now < eligible_at:
        return False
    if weak_point.last_mastery_decay_at is None:
        # Crossing the grace boundary applies one small adjustment. Future
        # adjustments require a full additional period.
        periods = 1
    else:
        periods = (now - weak_point.last_mastery_decay_at).days // _DECAY_PERIOD_DAYS
    if periods <= 0:
        return False

    weak_point.mastery_score = max(0, int(weak_point.mastery_score or 0) - periods * _DECAY_POINTS)
    weak_point.last_mastery_decay_at = now
    if weak_point.status == "resolved" and weak_point.mastery_score < 70:
        weak_point.status = "improving"
        weak_point.resolved_at = None
    return True
