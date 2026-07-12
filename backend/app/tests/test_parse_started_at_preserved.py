"""parse_with_retry must NOT overwrite parse_started_at set by the endpoint.

The endpoint sets parse_started_at when the user clicks parse. The
background task used to overwrite it with utc_now() when it started,
which reset the "已耗时 N 秒" elapsed timer and the timeout clock. The
task should only set parse_started_at when it is None (defensive
fallback), preserving the original start time.
"""
from datetime import timedelta, timezone

from app.core.timezone import utc_now
from app.models.material import Material
from app.services.material_parser import parse_with_retry


def _utc_instant(dt):
    """Normalize a datetime to a tz-aware UTC instant.

    SQLite strips tzinfo on read, so a value reloaded from the DB is
    naive even though it was stored as aware UTC. Treating a naive
    value as UTC lets us compare instants regardless of tzinfo.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def test_parse_with_retry_preserves_parse_started_at(
    db_session, sample_user, sample_course, monkeypatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", ".")
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="notes.txt",
        file_type="txt",
        file_path="notes.txt",
        status="processing",
    )
    db_session.add(material)
    db_session.commit()

    # The endpoint set parse_started_at 10 seconds ago.
    started = utc_now() - timedelta(seconds=10)
    material.parse_started_at = started
    db_session.commit()

    captured: dict = {}

    def fake_parse(path, file_type):
        # Capture the value visible to the parse function.
        captured["started_at"] = material.parse_started_at
        from app.tests._test_data import DIVERSE_OS_TEXT
        from app.retrieval.document_ir import DocumentPage, DocumentBlock
        text = DIVERSE_OS_TEXT * 2
        block = DocumentBlock(
            block_id="p1b0",
            page_no=1,
            block_type="body",
            reading_order=0,
            text=text,
            source_kind="txt",
        )
        return [DocumentPage(page_no=1, blocks=[block])]

    status, count = parse_with_retry(
        db_session, material, sample_user.id, parse_fn=fake_parse
    )

    assert status == "ready"
    assert count >= 1
    # The start time set by the endpoint must survive into the parse:
    # captured must still be ~10s ago (within 1s), NOT reset to ~now.
    captured_inst = _utc_instant(captured["started_at"])
    started_inst = _utc_instant(started)
    assert abs((captured_inst - started_inst).total_seconds()) < 1.0, (
        f"parse_started_at was overwritten: captured={captured['started_at']!r} "
        f"expected~={started!r}"
    )
    # And must still be the original value after parse completes.
    final_inst = _utc_instant(material.parse_started_at)
    assert abs((final_inst - started_inst).total_seconds()) < 1.0
