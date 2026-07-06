"""Keyword search endpoint.

``GET /api/v1/search?course_id=X&keyword=...&top_k=12`` runs keyword
retrieval over the parsed chunks of a course owned by the current user.
Cross-user access returns 404 so course existence is never leaked.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.course import Course
from app.models.user import User
from app.retrieval.search import keyword_search
from app.schemas.search import SearchResultItem, SearchResultListResponse

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


@router.get("", response_model=SearchResultListResponse)
def search(
    course_id: int = Query(...),
    keyword: str = Query("", max_length=200),
    top_k: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SearchResultListResponse:
    """Keyword search over a course's parsed material chunks."""
    _get_owned_course(db, course_id, current_user.id)
    results = keyword_search(db, course_id, keyword, top_k=top_k)
    items = [SearchResultItem(**r) for r in results]
    return SearchResultListResponse(items=items, total=len(items))
