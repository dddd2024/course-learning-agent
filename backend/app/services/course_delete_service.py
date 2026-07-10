"""Transactional course cleanup with a recoverable on-disk staging area."""
from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.citation import Citation
from app.models.concept_graph import ConceptCompareReport, ConceptEdge, ConceptNode
from app.models.conversation import Conversation, Message
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.models.plan import StudyTask, Todo
from app.models.quiz import Quiz, QuizItem, WeakPoint
from app.models.security_finding import MaterialSecurityFinding


def delete_course(db: Session, course: Course) -> None:
    """Remove all course-owned records atomically, then erase its files.

    Files are first renamed into a private trash directory.  A database error
    restores them; after commit, a failed physical erase leaves a recoverable
    trash directory instead of silently losing track of it.
    """
    course_id, user_id = course.id, course.user_id
    upload_root = Path(settings.UPLOAD_DIR).resolve()
    source_dir = upload_root / str(user_id) / str(course_id)
    trash_dir = upload_root / ".trash" / f"course-{user_id}-{course_id}"
    staged = False
    if source_dir.exists():
        trash_dir.parent.mkdir(parents=True, exist_ok=True)
        if trash_dir.exists():
            shutil.rmtree(trash_dir)
        source_dir.replace(trash_dir)
        staged = True
    try:
        material_ids = [r[0] for r in db.query(Material.id).filter(Material.course_id == course_id)]
        chunk_ids = [r[0] for r in db.query(MaterialChunk.id).filter(MaterialChunk.course_id == course_id)]
        conversation_ids = [r[0] for r in db.query(Conversation.id).filter(Conversation.course_id == course_id)]
        message_ids = [r[0] for r in db.query(Message.id).filter(Message.conversation_id.in_(conversation_ids))] if conversation_ids else []
        node_ids = [r[0] for r in db.query(ConceptNode.id).filter(ConceptNode.course_id == course_id)]
        task_ids = [r[0] for r in db.query(StudyTask.id).filter(StudyTask.course_id == course_id)]

        if message_ids:
            db.query(Citation).filter(Citation.message_id.in_(message_ids)).delete(synchronize_session=False)
        if chunk_ids:
            db.query(Citation).filter(Citation.chunk_id.in_(chunk_ids)).delete(synchronize_session=False)
        if conversation_ids:
            db.query(Message).filter(Message.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
            db.query(Conversation).filter(Conversation.id.in_(conversation_ids)).delete(synchronize_session=False)
        if node_ids:
            edge_ids = [r[0] for r in db.query(ConceptEdge.id).filter(
                (ConceptEdge.source_node_id.in_(node_ids)) | (ConceptEdge.target_node_id.in_(node_ids))
            )]
            db.query(ConceptCompareReport).filter(
                (ConceptCompareReport.source_node_id.in_(node_ids)) | (ConceptCompareReport.target_node_id.in_(node_ids)) |
                (ConceptCompareReport.edge_id.in_(edge_ids) if edge_ids else False)
            ).delete(synchronize_session=False)
            db.query(ConceptEdge).filter(ConceptEdge.id.in_(edge_ids)).delete(synchronize_session=False)
            db.query(ConceptNode).filter(ConceptNode.id.in_(node_ids)).delete(synchronize_session=False)
        if task_ids:
            db.query(Todo).filter(Todo.task_id.in_(task_ids)).delete(synchronize_session=False)
            db.query(StudyTask).filter(StudyTask.id.in_(task_ids)).delete(synchronize_session=False)
        db.query(Todo).filter(Todo.course_id == course_id).delete(synchronize_session=False)
        db.query(WeakPoint).filter(WeakPoint.course_id == course_id).delete(synchronize_session=False)
        quiz_ids = [r[0] for r in db.query(Quiz.id).filter(Quiz.course_id == course_id)]
        if quiz_ids:
            db.query(QuizItem).filter(QuizItem.quiz_id.in_(quiz_ids)).delete(synchronize_session=False)
            db.query(Quiz).filter(Quiz.id.in_(quiz_ids)).delete(synchronize_session=False)
        db.query(MaterialImage).filter(MaterialImage.course_id == course_id).delete(synchronize_session=False)
        if material_ids:
            db.query(Material).filter(Material.id.in_(material_ids)).update(
                {Material.active_version_id: None}, synchronize_session=False
            )
            db.query(MaterialSecurityFinding).filter(MaterialSecurityFinding.material_id.in_(material_ids)).delete(synchronize_session=False)
            db.query(MaterialVersion).filter(MaterialVersion.material_id.in_(material_ids)).delete(synchronize_session=False)
        db.query(MaterialChunk).filter(MaterialChunk.course_id == course_id).delete(synchronize_session=False)
        db.query(Material).filter(Material.course_id == course_id).delete(synchronize_session=False)
        db.query(KnowledgePoint).filter(KnowledgePoint.course_id == course_id).delete(synchronize_session=False)
        db.delete(course)
        db.commit()
    except Exception:
        db.rollback()
        if staged and trash_dir.exists() and not source_dir.exists():
            source_dir.parent.mkdir(parents=True, exist_ok=True)
            trash_dir.replace(source_dir)
        raise
    if staged:
        shutil.rmtree(trash_dir, ignore_errors=False)
