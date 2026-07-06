"""Citations endpoint.

``GET /api/v1/messages/{message_id}/citations`` returns the citations
persisted for an assistant message. Ownership is verified through the
``message -> conversation -> course -> user_id`` chain so a user can
only fetch citations for their own messages; cross-user access returns
404 (existence is never leaked).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.citation import Citation
from app.models.conversation import Conversation, Message
from app.models.course import Course
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.user import User
from app.schemas.citation import CitationListResponse, CitationResponse

router = APIRouter()


def _get_owned_message(
    db: Session, message_id: int, user_id: int
) -> Message:
    """Return the message if it belongs to ``user_id``, else 404.

    The ownership chain is:
    message -> conversation -> course -> user_id.
    """
    row = (
        db.query(Message, Conversation, Course)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Course, Course.id == Conversation.course_id)
        .filter(Message.id == message_id, Course.user_id == user_id)
        .first()
    )
    if row is None:
        raise NotFoundException(message="消息不存在")
    return row[0]


@router.get(
    "/{message_id}/citations",
    response_model=CitationListResponse,
)
def list_citations(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CitationListResponse:
    """List citations persisted for an assistant message."""
    _get_owned_message(db, message_id, current_user.id)

    rows = (
        db.query(Citation, MaterialChunk, Material)
        .join(MaterialChunk, MaterialChunk.id == Citation.chunk_id)
        .join(Material, Material.id == MaterialChunk.material_id)
        .filter(Citation.message_id == message_id)
        .order_by(Citation.id.asc())
        .all()
    )

    items: list[CitationResponse] = []
    for cite, chunk, material in rows:
        items.append(
            CitationResponse(
                chunk_id=cite.chunk_id,
                material_id=chunk.material_id,
                material_name=material.filename,
                page_no=cite.page_no,
                quote_text=cite.quote_text or "",
                confidence=cite.confidence or 0.0,
            )
        )
    return CitationListResponse(items=items, total=len(items))
