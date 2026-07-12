"""Quiz generation, submission, and weak-point endpoints.

``POST /api/v1/quizzes`` runs the ``QuizAgent`` over the course's
knowledge points, persists ``Quiz`` + ``QuizItem`` rows, and returns
the quiz (without answers).

``GET /api/v1/quizzes`` / ``GET /api/v1/quizzes/{id}`` list / fetch
quizzes for the current user (answers never leak before submission).

``GET /api/v1/quizzes/{id}/result`` returns the persisted result of a
submitted quiz so it can be reviewed again without re-submitting it.

``POST /api/v1/quizzes/{id}/submit`` grades the submitted answers,
fills ``score`` / ``status`` / per-item ``user_answer`` /
``is_correct``, and writes ``WeakPoint`` rows for the knowledge points
the user got wrong (incrementing ``wrong_count`` on repeats).

``GET /api/v1/courses/{course_id}/weak-points`` returns the user's
weak points for a course.

All queries are scoped by ``current_user.id`` so a resource owned by
another user is invisible (returned as 404) so existence is never
leaked.
"""
import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.agents.audit import AgentAudit
from app.agents.quiz import generate_quiz
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import BusinessException, NotFoundException
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.quiz import Quiz, QuizItem, WeakPoint
from app.models.plan import StudyTask, Todo
from app.models.user import User
from app.schemas.quiz import (
    QuizCreate,
    QuizItemOut,
    QuizListResponse,
    QuizOut,
    QuizResultItemOut,
    QuizResultOut,
    QuizSubmit,
    WeakPointListResponse,
    WeakPointOut,
)
from app.services.llm_config_service import (
    build_user_config,
    get_active_config,
)
from app.services.weak_point_progress import apply_mastery_decay

logger = logging.getLogger(__name__)
router = APIRouter()
weak_points_router = APIRouter()

_PROMPT_VERSION = "quiz_generate_v1"


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


def _get_owned_quiz(db: Session, quiz_id: int, user_id: int) -> Quiz:
    """Return the quiz if it belongs to ``user_id``, else 404."""
    quiz = (
        db.query(Quiz)
        .filter(Quiz.id == quiz_id, Quiz.user_id == user_id)
        .first()
    )
    if quiz is None:
        raise NotFoundException(message="测验不存在")
    return quiz


def _quiz_to_response(
    quiz: Quiz,
    partial_generation: bool = False,
    insufficient_evidence: bool = False,
) -> QuizOut:
    """Build a ``QuizOut`` (with items, without answers) from a ``Quiz``."""
    items = [
        QuizItemOut.model_validate(item)
        for item in sorted(quiz.items, key=lambda i: i.order_index)
    ]
    return QuizOut(
        id=quiz.id,
        course_id=quiz.course_id,
        title=quiz.title,
        question_count=quiz.question_count,
        status=quiz.status,
        score=quiz.score,
        created_at=quiz.created_at,
        items=items,
        partial_generation=partial_generation,
        insufficient_evidence=insufficient_evidence,
    )


def _normalise_option_answer(value) -> str:
    if isinstance(value, list):
        return ",".join(sorted({_normalise_option_answer(v) for v in value if _normalise_option_answer(v)}))
    text = str(value or "").strip().upper()
    return text[0] if text and text[0].isalpha() else text


def _legacy_rubric(answer: str) -> list[dict]:
    """Build an explainable fallback rubric for quizzes created before this feature."""
    terms = list(dict.fromkeys(
        term.lower()
        for term in re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}", answer)
    ))[:8]
    return [{"criterion": f"说明“{term}”", "keywords": [term]} for term in terms]


def _short_answer_feedback(item: QuizItem, user_answer) -> tuple[bool, list[dict], bool]:
    """Return deterministic scoring details for a short answer.

    QUIZ-V3-03: supports weighted rubric criteria. When the rubric has
    ``weight`` fields, the total score is computed as a weighted sum.
    Per-criterion details include hit keywords, missing points, and
    individual scores. ``legacy_scoring`` is set to True for old items
    without weighted rubrics. ``needs_human_review`` is set for
    borderline scores (0.4 <= score < 0.6).
    """
    try:
        rubric = json.loads(item.rubric_json or "[]")
    except (TypeError, json.JSONDecodeError):
        rubric = []
    if not isinstance(rubric, list) or not rubric:
        rubric = _legacy_rubric(item.answer or "")

    # QUIZ-V3-03: detect whether this is a weighted rubric.
    has_weights = any(
        isinstance(c, dict) and "weight" in c and c.get("weight", 0) > 0
        for c in rubric
    )
    legacy_scoring = not has_weights

    text = str(user_answer or "").strip().lower()
    feedback: list[dict] = []
    total_weight = 0.0
    earned_weight = 0.0

    for criterion in rubric:
        if not isinstance(criterion, dict):
            continue
        keywords = [
            str(value).strip().lower()
            for value in criterion.get("keywords", [])
            if str(value).strip()
        ]
        if not keywords:
            continue
        met = any(keyword in text for keyword in keywords)
        weight = float(criterion.get("weight", 0.0)) if not legacy_scoring else 0.0
        if legacy_scoring:
            weight = 1.0 / len(rubric)
        total_weight += weight
        if met:
            earned_weight += weight
        hit_keywords = [kw for kw in keywords if kw in text]
        missing_keywords = [kw for kw in keywords if kw not in text]
        feedback.append({
            "criterion": str(criterion.get("criterion") or "关键要点"),
            "met": met,
            "keywords": keywords,
            "hit_keywords": hit_keywords,
            "missing_keywords": missing_keywords,
            "weight": round(weight, 4),
            "score": 1.0 if met else 0.0,
            "message": "已覆盖该要点" if met else "尚未说明该要点",
            "evidence_ids": criterion.get("evidence_ids", []),
            "required": criterion.get("required", True),
        })

    if not feedback:
        return False, [], True

    if legacy_scoring:
        ratio = sum(entry["met"] for entry in feedback) / len(feedback)
        correct = ratio >= 0.5
        needs_review = 0.4 <= ratio < 0.6
        # Add legacy_scoring flag to each feedback entry.
        for entry in feedback:
            entry["legacy_scoring"] = True
    else:
        total_score = earned_weight / total_weight if total_weight > 0 else 0.0
        correct = total_score >= 0.5
        needs_review = 0.4 <= total_score < 0.6
        for entry in feedback:
            entry["legacy_scoring"] = False
        # Add total score summary.
        feedback.append({
            "total_score": round(total_score, 4),
            "earned_weight": round(earned_weight, 4),
            "total_weight": round(total_weight, 4),
            "legacy_scoring": False,
            "needs_human_review": needs_review,
        })

    return correct, feedback, needs_review


def _grade_item_details(item: QuizItem, user_answer) -> tuple[bool, list[dict], bool]:
    """Grade an item and return (correct, feedback, needs_human_review)."""
    answer = (item.answer or "").strip()
    user_answer = _normalise_option_answer(user_answer) if item.question_type in ("choice", "multiple_choice", "true_false") else str(user_answer or "").strip()
    if not user_answer:
        return False, [], item.question_type == "short_answer"
    if item.question_type in ("choice", "true_false"):
        return user_answer == _normalise_option_answer(answer), [], False
    if item.question_type == "multiple_choice":
        try:
            correct = json.loads(answer) if answer.startswith("[") else answer.split(",")
        except json.JSONDecodeError:
            correct = answer.split(",")
        return set(filter(None, user_answer.split(","))) == set(filter(None, _normalise_option_answer(correct).split(","))), [], False
    if item.question_type == "short_answer":
        return _short_answer_feedback(item, user_answer)
    # Unknown type: fall back to exact match.
    return user_answer == answer, [], False


def _grade_item(item: QuizItem, user_answer) -> bool:
    """Compatibility wrapper for callers that only need the score flag."""
    return _grade_item_details(item, user_answer)[0]


def _upsert_weak_point(
    db: Session,
    user_id: int,
    course_id: int,
    knowledge_point_id: int,
    correct: bool,
) -> None:
    """Insert or increment a ``WeakPoint`` row."""
    wp = (
        db.query(WeakPoint)
        .filter(
            WeakPoint.user_id == user_id,
            WeakPoint.course_id == course_id,
            WeakPoint.knowledge_point_id == knowledge_point_id,
        )
        .first()
    )
    now = datetime.now()
    if wp is None:
        wp = WeakPoint(
            user_id=user_id,
            course_id=course_id,
            knowledge_point_id=knowledge_point_id,
            wrong_count=0 if correct else 1,
            correct_count=1 if correct else 0,
            consecutive_correct=1 if correct else 0,
            mastery_score=15 if correct else 0,
            last_wrong_at=None if correct else now,
            last_practiced_at=now,
            status="improving" if correct else "active",
        )
        db.add(wp)
    else:
        wp.last_practiced_at = now
        if correct:
            wp.correct_count += 1
            wp.consecutive_correct += 1
            wp.mastery_score = min(100, wp.mastery_score + 20)
            if wp.consecutive_correct >= 3 and wp.mastery_score >= 70:
                wp.status, wp.resolved_at = "resolved", now
            else:
                wp.status = "improving"
        else:
            wp.wrong_count += 1
            wp.consecutive_correct = 0
            wp.mastery_score = max(0, wp.mastery_score - 25)
            wp.status, wp.resolved_at, wp.last_wrong_at = "active", None, now
    db.flush()


@router.post("", response_model=QuizOut)
def create_quiz(
    payload: QuizCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuizOut:
    """Generate a quiz for a course's knowledge points."""
    course = _get_owned_course(db, payload.course_id, current_user.id)

    # Resolve the knowledge points to quiz on.
    if payload.knowledge_point_ids:
        rows = (
            db.query(KnowledgePoint)
            .filter(
                KnowledgePoint.course_id == payload.course_id,
                KnowledgePoint.user_id == current_user.id,
                KnowledgePoint.status == "active",
                KnowledgePoint.id.in_(payload.knowledge_point_ids),
            )
            .order_by(KnowledgePoint.id.asc())
            .all()
        )
    else:
        rows = (
            db.query(KnowledgePoint)
            .filter(
                KnowledgePoint.course_id == payload.course_id,
                KnowledgePoint.user_id == current_user.id,
                KnowledgePoint.status == "active",
            )
            .order_by(KnowledgePoint.id.asc())
            .all()
        )

    if not rows:
        raise BusinessException(message="课程暂无知识点，请先生成知识点")

    active_config = get_active_config(db, current_user.id)
    user_config = build_user_config(active_config) if active_config else None

    quiz_output = generate_quiz(
        db=db,
        user_id=current_user.id,
        course_id=payload.course_id,
        knowledge_points=rows,
        course_name=course.name,
        question_count=payload.question_count,
        user_config=user_config,
    )
    insufficient_evidence = quiz_output.get("insufficient_evidence", False)
    if not quiz_output.get("items"):
        raise BusinessException(message="资料证据不足，未创建空测验；请补充资料或重新解析", status_code=422)

    quiz = Quiz(
        user_id=current_user.id,
        course_id=payload.course_id,
        title=quiz_output.get("title", f"{course.name} 测验"),
        question_count=len(quiz_output.get("items", [])),
        status="draft",
    )
    db.add(quiz)
    db.flush()

    for item_data in quiz_output.get("items", []):
        item = QuizItem(
            quiz_id=quiz.id,
            knowledge_point_id=item_data.get("knowledge_point_id"),
            question_type=item_data.get("question_type", "short_answer"),
            question_text=item_data.get("question_text", ""),
            options=json.dumps(
                item_data.get("options", []), ensure_ascii=False
            ),
            answer=item_data.get("answer", ""),
            explanation=item_data.get("explanation", ""),
            difficulty=item_data.get("difficulty"),
            source_evidence_ids=json.dumps(item_data.get("source_evidence_ids", [])),
            evidence_snapshot=json.dumps(item_data.get("source_evidence_ids", [])),
            # QUIZ-V3-01: store source_evidence for grounding verification.
            source_evidence=json.dumps(
                item_data.get("source_evidence", []), ensure_ascii=False
            ),
            verification_status=item_data.get("verification_status", "verified"),
            rubric_json=json.dumps(item_data.get("rubric", []), ensure_ascii=False),
            order_index=item_data.get("order_index", 0),
        )
        db.add(item)

    db.commit()
    db.refresh(quiz)
    # QUIZ-V3-02: pass partial_generation flag to the response.
    partial_gen = quiz_output.get("partial_generation", False)
    return _quiz_to_response(
        quiz,
        partial_generation=partial_gen,
        insufficient_evidence=insufficient_evidence,
    )


@router.get("", response_model=QuizListResponse)
def list_quizzes(
    course_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuizListResponse:
    """List the current user's quizzes with optional course filter."""
    query = db.query(Quiz).filter(Quiz.user_id == current_user.id)
    if course_id is not None:
        query = query.filter(Quiz.course_id == course_id)
    rows = query.order_by(Quiz.id.asc()).all()
    items = [_quiz_to_response(r) for r in rows]
    return QuizListResponse(items=items, total=len(items))


@router.get("/{quiz_id}", response_model=QuizOut)
def get_quiz(
    quiz_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuizOut:
    """Return a single quiz with its items (answers excluded)."""
    quiz = _get_owned_quiz(db, quiz_id, current_user.id)
    return _quiz_to_response(quiz)


@router.get("/{quiz_id}/result", response_model=QuizResultOut)
def get_quiz_result(
    quiz_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuizResultOut:
    """Return a submitted quiz's persisted answers and grading details."""
    quiz = _get_owned_quiz(db, quiz_id, current_user.id)
    if quiz.status != "submitted":
        raise BusinessException(message="该测验尚未提交，暂无结果")

    items = []
    for item in sorted(quiz.items, key=lambda i: i.order_index):
        _, rubric_feedback, needs_review = _grade_item_details(item, item.user_answer)
        items.append(QuizResultItemOut(
            id=item.id,
            question_type=item.question_type,
            question_text=item.question_text,
            options=item.options,
            correct_answer=item.answer or "",
            user_answer=item.user_answer,
            is_correct=item.is_correct,
            explanation=item.explanation,
            knowledge_point_id=item.knowledge_point_id,
            rubric_feedback=rubric_feedback,
            needs_review=needs_review,
            source_evidence=item.source_evidence or "[]",
            verification_status=getattr(item, "verification_status", "verified") or "verified",
        ))
    return QuizResultOut(
        id=quiz.id,
        score=quiz.score or 0,
        total=len(items),
        items=items,
    )


@router.delete("/{quiz_id}", status_code=204)
def delete_quiz(
    quiz_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a quiz (and its items) owned by the current user.

    QuizItem rows are also removed via the ``all, delete-orphan`` cascade
    on ``Quiz.items``, but we delete them explicitly first for clarity
    and to keep the operation robust against any cascade quirk.
    """
    quiz = _get_owned_quiz(db, quiz_id, current_user.id)
    db.query(QuizItem).filter(QuizItem.quiz_id == quiz_id).delete()
    db.delete(quiz)
    db.commit()


@router.post("/{quiz_id}/submit", response_model=QuizResultOut)
def submit_quiz(
    quiz_id: int,
    payload: QuizSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuizResultOut:
    """Grade a submitted quiz and record weak points for wrong answers."""
    quiz = _get_owned_quiz(db, quiz_id, current_user.id)

    if quiz.status == "submitted":
        raise BusinessException(message="该测验已提交，不可重复提交")

    # Index items by id for O(1) lookup.
    items_by_id: dict[int, QuizItem] = {item.id: item for item in quiz.items}
    answer_map: dict[int, str | list[str]] = {
        a.item_id: a.user_answer for a in payload.answers
    }

    # Audit the submission.
    run_id: int | None = None
    try:
        run = AgentAudit.create_run(
            db,
            user_id=current_user.id,
            run_type="quiz",
            input_summary={
                "quiz_id": quiz_id,
                "answer_count": len(payload.answers),
            },
            prompt_version=_PROMPT_VERSION,
            model_name="mock",
            provider="mock",
            config_id=None,
        )
        run_id = run.id
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.create_run(quiz submit) failed: %s", exc)

    score = 0
    result_items: list[QuizResultItemOut] = []
    practiced: dict[int, bool] = {}
    for item in sorted(quiz.items, key=lambda i: i.order_index):
        user_answer = answer_map.get(item.id, "")
        is_correct, rubric_feedback, needs_review = _grade_item_details(item, user_answer)
        item.user_answer = json.dumps(user_answer, ensure_ascii=False) if isinstance(user_answer, list) else user_answer
        item.is_correct = 1 if is_correct else 0
        if is_correct:
            score += 1
        elif not needs_review:
            # Record each knowledge point once per submitted quiz. A generated
            # quiz may contain multiple questions for the same point; counting
            # each duplicate made severity depend on generator composition
            # instead of the learner's number of failed review attempts.
            if item.knowledge_point_id is not None:
                practiced[item.knowledge_point_id] = False
        if is_correct and item.knowledge_point_id is not None and item.knowledge_point_id not in practiced:
            practiced[item.knowledge_point_id] = True
        result_items.append(
            QuizResultItemOut(
                id=item.id,
                question_type=item.question_type,
                question_text=item.question_text,
                options=item.options,
                correct_answer=item.answer or "",
                user_answer=item.user_answer,
                is_correct=item.is_correct,
                explanation=item.explanation,
                knowledge_point_id=item.knowledge_point_id,
                rubric_feedback=rubric_feedback,
                needs_review=needs_review,
                source_evidence=item.source_evidence or "[]",
                verification_status=getattr(item, "verification_status", "verified") or "verified",
            )
        )

    for knowledge_point_id, correct in practiced.items():
        if correct and not db.query(WeakPoint.id).filter(
            WeakPoint.user_id == current_user.id,
            WeakPoint.course_id == quiz.course_id,
            WeakPoint.knowledge_point_id == knowledge_point_id,
        ).first():
            continue
        _upsert_weak_point(
            db,
            user_id=current_user.id,
            course_id=quiz.course_id,
            knowledge_point_id=knowledge_point_id,
            correct=correct,
        )

    quiz.score = score
    quiz.status = "submitted"

    db.commit()
    db.refresh(quiz)

    if run_id is not None:
        try:
            AgentAudit.finish_run(
                db,
                run_id=run_id,
                status="success",
                output_summary={
                    "quiz_id": quiz_id,
                    "score": score,
                    "total": len(items_by_id),
                },
            )
            db.commit()
        except Exception as exc:  # pragma: no cover - audit must not break flow
            logger.warning("AgentAudit.finish_run(quiz submit) failed: %s", exc)

    return QuizResultOut(
        id=quiz.id,
        score=score,
        total=len(items_by_id),
        items=result_items,
    )


@weak_points_router.get("/{course_id}/weak-points", response_model=WeakPointListResponse)
def list_weak_points(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WeakPointListResponse:
    """List the current user's weak points for a course."""
    _get_owned_course(db, course_id, current_user.id)

    # Use an inner join (not outerjoin) so WeakPoint rows whose
    # KnowledgePoint has been deleted (e.g. when points are regenerated)
    # are filtered out instead of returning an empty title.
    rows = (
        db.query(WeakPoint, KnowledgePoint)
        .join(
            KnowledgePoint,
            KnowledgePoint.id == WeakPoint.knowledge_point_id,
        )
        .filter(
            WeakPoint.user_id == current_user.id,
            WeakPoint.course_id == course_id,
        )
        .order_by(WeakPoint.id.asc())
        .all()
    )
    if any(apply_mastery_decay(wp) for wp, _ in rows):
        db.commit()
    rows.sort(
        key=lambda row: (
            row[0].status == "resolved",
            row[0].mastery_score,
            -(row[0].wrong_count or 0),
            row[0].last_wrong_at or datetime.min,
        )
    )
    items = [
        WeakPointOut(
            id=wp.id,
            course_id=wp.course_id,
            knowledge_point_id=wp.knowledge_point_id,
            knowledge_point_title=kp.title if kp is not None else "",
            wrong_count=wp.wrong_count,
            last_wrong_at=wp.last_wrong_at,
            correct_count=wp.correct_count,
            consecutive_correct=wp.consecutive_correct,
            mastery_score=wp.mastery_score,
            status=wp.status,
            last_mastery_decay_at=wp.last_mastery_decay_at,
        )
        for wp, kp in rows
    ]
    return WeakPointListResponse(items=items, total=len(items))
