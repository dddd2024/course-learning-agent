"""Transactional material deletion with recoverable storage cleanup."""
from __future__ import annotations
import json
import shutil
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.models.citation import Citation
from app.models.knowledge_point import KnowledgePoint
from app.models.quiz import QuizItem
from app.models.security_finding import MaterialSecurityFinding
from app.retrieval.search import remove_from_fts_index


def delete_material(db: Session, material: Material) -> dict[str, int]:
    root = Path(settings.UPLOAD_DIR) / material.file_path
    folder = root.parent
    staged = folder.with_name(folder.name + ".deleting")
    if folder.exists():
        folder.replace(staged)
    try:
        chunk_ids = [row[0] for row in db.query(MaterialChunk.id).filter(MaterialChunk.material_id == material.id).all()]
        # Remove retrieval rows before deleting ORM rows; the operation is
        # idempotent and prevents deleted evidence from surviving in FTS.
        if chunk_ids:
            remove_from_fts_index(db, chunk_ids)
        counts = {"citations": 0, "knowledge_point_sources": 0, "quiz_evidence": 0}
        if chunk_ids:
            counts["citations"] = db.query(Citation).filter(Citation.chunk_id.in_(chunk_ids)).delete(synchronize_session=False)
            for point in db.query(KnowledgePoint).filter(KnowledgePoint.course_id == material.course_id).all():
                try:
                    source_ids = json.loads(point.source_chunk_ids or "[]")
                except (TypeError, json.JSONDecodeError):
                    source_ids = []
                kept = [value for value in source_ids if value not in chunk_ids]
                if len(kept) != len(source_ids):
                    point.source_chunk_ids = json.dumps(kept)
                    point.status = "archived" if not kept else point.status
                    counts["knowledge_point_sources"] += len(source_ids) - len(kept)
            for item in db.query(QuizItem).all():
                try:
                    evidence = json.loads(item.source_evidence or "[]")
                except (TypeError, json.JSONDecodeError):
                    evidence = []
                kept_evidence = [entry for entry in evidence if entry.get("chunk_id") not in chunk_ids]
                if len(kept_evidence) != len(evidence):
                    item.source_evidence = json.dumps(kept_evidence, ensure_ascii=False)
                    item.verification_status = "invalid" if not kept_evidence else item.verification_status
                    counts["quiz_evidence"] += len(evidence) - len(kept_evidence)
        counts.update({"images": db.query(MaterialImage).filter(MaterialImage.material_id == material.id).delete(synchronize_session=False), "pages": db.query(MaterialPage).filter(MaterialPage.material_id == material.id).delete(synchronize_session=False), "page_assets": db.query(MaterialPageAsset).filter(MaterialPageAsset.material_id == material.id).delete(synchronize_session=False), "security_findings": db.query(MaterialSecurityFinding).filter(MaterialSecurityFinding.material_id == material.id).delete(synchronize_session=False), "chunks": db.query(MaterialChunk).filter(MaterialChunk.material_id == material.id).delete(synchronize_session=False), "versions": db.query(MaterialVersion).filter(MaterialVersion.material_id == material.id).delete(synchronize_session=False)})
        db.delete(material)
        db.commit()
    except Exception:
        db.rollback()
        if staged.exists(): staged.replace(folder)
        raise
    if staged.exists():
        shutil.rmtree(staged)
    return counts
