"""Tests for UTC timezone handling in API schemas."""
from datetime import datetime, timezone

from app.schemas.conversation import ConversationResponse
from app.schemas.message import MessageResponse


def test_conversation_response_attaches_utc():
    """ConversationResponse should attach UTC tzinfo to naive datetimes."""
    naive = datetime(2026, 7, 10, 13, 25, 0)  # no tzinfo
    resp = ConversationResponse(
        id=1, user_id=1, course_id=1, title="test",
        created_at=naive, updated_at=naive,
    )
    assert resp.created_at.tzinfo is not None, (
        "created_at should have tzinfo after validation"
    )
    # Should be UTC (+00:00)
    assert resp.created_at.utcoffset().total_seconds() == 0


def test_message_response_attaches_utc():
    """MessageResponse should attach UTC tzinfo to naive datetimes."""
    naive = datetime(2026, 7, 10, 13, 25, 0)
    resp = MessageResponse(
        id=1, role="user", content="test",
        created_at=naive,
    )
    assert resp.created_at.tzinfo is not None
    assert resp.created_at.utcoffset().total_seconds() == 0
