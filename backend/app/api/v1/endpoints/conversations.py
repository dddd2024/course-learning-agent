"""Conversation CRUD endpoints.

All queries are scoped by ``current_user.id`` to enforce per-user data
isolation. A course owned by another user is invisible (returned as 404)
so existence is never leaked.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.conversation import Conversation
from app.models.course import Course
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
)

router = APIRouter()


def _get_owned_course(db: Session, course_id: int, user_id: int) -> Course:
    """Return the course if it belongs to ``user_id``, else 404."""
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.user_id == user_id)
        .first()
    )
    if course is None:
        raise NotFoundException(message="课程不存在")
    return course


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=201,
)
def create_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationResponse:
    """Create a conversation bound to a course owned by the current user."""
    _get_owned_course(db, payload.course_id, current_user.id)
    conversation = Conversation(
        user_id=current_user.id,
        course_id=payload.course_id,
        title=payload.title,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return ConversationResponse.model_validate(conversation)


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    course_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationListResponse:
    """List conversations for a course owned by the current user."""
    _get_owned_course(db, course_id, current_user.id)
    items = (
        db.query(Conversation)
        .filter(
            Conversation.course_id == course_id,
            Conversation.user_id == current_user.id,
        )
        .order_by(Conversation.id.desc())
        .all()
    )
    return ConversationListResponse(
        items=[ConversationResponse.model_validate(c) for c in items],
        total=len(items),
    )
