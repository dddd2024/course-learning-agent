"""Course CRUD endpoints.

All queries are scoped by ``current_user.id`` to enforce per-user data
isolation. A course owned by another user is invisible (returned as 404)
so existence is never leaked.
"""
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.course import Course
from app.models.user import User
from app.schemas.course import (
    CourseCreate,
    CourseListResponse,
    CourseResponse,
    CourseUpdate,
)

router = APIRouter()


def _get_owned_course(
    db: Session, course_id: int, user_id: int
) -> Course:
    """Return the course if it belongs to ``user_id``, else 404.

    Centralises the user-scoped lookup so isolation is consistent across
    GET / PUT / DELETE.
    """
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.user_id == user_id)
        .first()
    )
    if course is None:
        raise NotFoundException(message="课程不存在")
    return course


@router.get("", response_model=CourseListResponse)
def list_courses(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CourseListResponse:
    """List the current user's courses with optional keyword search."""
    query = db.query(Course).filter(Course.user_id == current_user.id)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (Course.name.like(like))
            | (Course.teacher.like(like))
            | (Course.description.like(like))
        )

    total = query.count()
    items = (
        query.order_by(Course.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return CourseListResponse(
        items=[CourseResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=CourseResponse, status_code=201)
def create_course(
    payload: CourseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CourseResponse:
    """Create a course bound to the authenticated user."""
    course = Course(
        user_id=current_user.id,
        name=payload.name,
        teacher=payload.teacher,
        semester=payload.semester,
        description=payload.description,
        color=payload.color,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return CourseResponse.model_validate(course)


@router.get("/{course_id}", response_model=CourseResponse)
def get_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CourseResponse:
    """Return one course owned by the current user (404 otherwise)."""
    course = _get_owned_course(db, course_id, current_user.id)
    return CourseResponse.model_validate(course)


@router.put("/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: int,
    payload: CourseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CourseResponse:
    """Update a course owned by the current user (404 otherwise)."""
    course = _get_owned_course(db, course_id, current_user.id)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(course, field, value)
    db.commit()
    db.refresh(course)
    return CourseResponse.model_validate(course)


@router.delete("/{course_id}", status_code=204)
def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a course owned by the current user (404 otherwise)."""
    course = _get_owned_course(db, course_id, current_user.id)
    db.delete(course)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
