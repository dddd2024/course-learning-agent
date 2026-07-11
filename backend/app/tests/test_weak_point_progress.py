"""Regression tests for weak-point forgetting and recovery semantics."""
from datetime import datetime, timedelta

from app.models.quiz import WeakPoint
from app.services.weak_point_progress import apply_mastery_decay


def test_mastery_decays_once_after_long_practice_gap() -> None:
    weak_point = WeakPoint(
        mastery_score=80,
        status="resolved",
        last_practiced_at=datetime(2026, 1, 1),
    )
    now = datetime(2026, 2, 5)

    assert apply_mastery_decay(weak_point, now) is True
    assert weak_point.mastery_score == 75
    assert weak_point.status == "resolved"
    assert weak_point.last_mastery_decay_at == now
    # Re-reading on the same day cannot decay a second time.
    assert apply_mastery_decay(weak_point, now) is False
    assert weak_point.mastery_score == 75


def test_long_decay_reopens_resolved_point_when_mastery_drops() -> None:
    weak_point = WeakPoint(
        mastery_score=72,
        status="resolved",
        resolved_at=datetime(2026, 1, 1),
        last_practiced_at=datetime(2026, 1, 1),
    )

    assert apply_mastery_decay(weak_point, datetime(2026, 3, 10)) is True
    assert weak_point.mastery_score < 70
    assert weak_point.status == "improving"
    assert weak_point.resolved_at is None


def test_recent_practice_does_not_decay() -> None:
    weak_point = WeakPoint(
        mastery_score=60,
        last_practiced_at=datetime.now() - timedelta(days=20),
    )
    assert apply_mastery_decay(weak_point) is False
    assert weak_point.mastery_score == 60
