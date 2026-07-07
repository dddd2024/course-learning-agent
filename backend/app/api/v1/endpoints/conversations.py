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
from app.models.conversation import Conversation, Message
from app.models.course import Course
from app.models.citation import Citation
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
)
from app.schemas.message import (
    CitationBrief,
    MessageListResponse,
    MessageResponse,
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


def _get_owned_conversation(db: Session, conv_id: int, user_id: int) -> Conversation:
    """Return the conversation if it belongs to ``user_id``, else 404."""
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conv_id, Conversation.user_id == user_id)
        .first()
    )
    if conv is None:
        raise NotFoundException(message="对话不存在")
    return conv


@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="获取对话历史消息",
)
def list_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageListResponse:
    """Return user+assistant messages for a conversation, scoped to the owner.

    Cross-user access returns 404 so existence is never leaked. Assistant
    messages include their bound citations (with material_name / page_no)
    reconstructed via MaterialChunk → Material join.
    """
    conv = _get_owned_conversation(db, conversation_id, current_user.id)
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.id.asc())
        .all()
    )
    items: list[MessageResponse] = []
    for m in msgs:
        rows = (
            db.query(Citation, Material.filename)
            .join(MaterialChunk, Citation.chunk_id == MaterialChunk.id)
            .join(Material, MaterialChunk.material_id == Material.id)
            .filter(Citation.message_id == m.id)
            .all()
        )
        briefs: list[CitationBrief] = []
        for cite, filename in rows:
            label = (
                f"{filename} · 第 {cite.page_no} 页"
                if cite.page_no
                else filename
            )
            briefs.append(
                CitationBrief(
                    chunk_id=cite.chunk_id,
                    quote_text=cite.quote_text,
                    page_no=cite.page_no,
                    material_name=filename,
                    display_label=label,
                )
            )
        items.append(
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                answer_json=m.answer_json,
                citations=briefs,
                created_at=m.created_at,
            )
        )
    return MessageListResponse(items=items, total=len(items))
