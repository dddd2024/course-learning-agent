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
    ConversationUpdate,
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

    Citations are loaded with a single batched query keyed by ``message_id``
    instead of one query per message, to avoid an N+1 when a conversation
    has many messages. ``selectinload(Message.citations)`` is not used
    because the Message/Citation models declare no ORM relationship and
    such a load still could not fetch the joined ``Material.filename``
    needed for ``display_label``; a manual batch query handles both.
    """
    conv = _get_owned_conversation(db, conversation_id, current_user.id)
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.id.asc())
        .all()
    )

    # Batch-load citations (with material filename) for every message at
    # once, then group them by message_id. This replaces the previous
    # per-message query issued inside the loop (an N+1).
    msg_ids = [m.id for m in msgs]
    citations_by_msg: dict[int, list[CitationBrief]] = {}
    if msg_ids:
        rows = (
            db.query(Citation, Material.filename)
            .join(MaterialChunk, Citation.chunk_id == MaterialChunk.id)
            .join(Material, MaterialChunk.material_id == Material.id)
            .filter(Citation.message_id.in_(msg_ids))
            .all()
        )
        for cite, filename in rows:
            label = (
                f"{filename} · 第 {cite.page_no} 页"
                if cite.page_no
                else filename
            )
            citations_by_msg.setdefault(cite.message_id, []).append(
                CitationBrief(
                    chunk_id=cite.chunk_id,
                    quote_text=cite.quote_text,
                    page_no=cite.page_no,
                    material_name=filename,
                    display_label=label,
                    claim_text=cite.claim_text,
                    support_status=cite.support_status or "weak",
                    verification_reason=cite.verification_reason,
                )
            )

    items: list[MessageResponse] = []
    for m in msgs:
        items.append(
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                answer_json=m.answer_json,
                citations=citations_by_msg.get(m.id, []),
                created_at=m.created_at,
            )
        )
    return MessageListResponse(items=items, total=len(items))


@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="重命名对话",
)
def update_conversation(
    conversation_id: int,
    update: ConversationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationResponse:
    """Rename a conversation owned by the current user.

    Cross-user access returns 404 so existence is never leaked.
    """
    conv = _get_owned_conversation(db, conversation_id, current_user.id)
    conv.title = update.title
    db.commit()
    db.refresh(conv)
    return ConversationResponse.model_validate(conv)


@router.delete(
    "/{conversation_id}",
    status_code=204,
    summary="删除对话",
)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a conversation and all of its messages and citations.

    The Message/Citation models declare no ORM relationship and the
    foreign keys carry no ``ON DELETE CASCADE``, so child rows must be
    removed explicitly to avoid integrity errors: citations first (they
    reference ``messages.id``), then messages, then the conversation.

    Cross-user access returns 404 so existence is never leaked.
    """
    conv = _get_owned_conversation(db, conversation_id, current_user.id)
    # Gather message ids for this conversation, then delete their
    # citations before removing the messages themselves.
    msg_ids = [
        mid
        for (mid,) in db.query(Message.id)
        .filter(Message.conversation_id == conv.id)
        .all()
    ]
    if msg_ids:
        db.query(Citation).filter(
            Citation.message_id.in_(msg_ids)
        ).delete(synchronize_session=False)
    db.query(Message).filter(
        Message.conversation_id == conv.id
    ).delete(synchronize_session=False)
    db.delete(conv)
    db.commit()
