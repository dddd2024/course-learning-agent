from __future__ import annotations

import pytest

from app.core.exceptions import NotFoundException
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.retrieval.document_ir import DocumentPage
from app.retrieval.search import rebuild_material_fts
from app.services.chat_service import _selection_chunks, validate_selection_context


def _material(db, user, course):
    material = Material(
        user_id=user.id,
        course_id=course.id,
        filename="reader.pdf",
        file_type="pdf",
        file_path="reader.pdf",
        status="ready",
    )
    db.add(material)
    db.flush()
    version = MaterialVersion(material_id=material.id, version=1, status="ready")
    db.add(version)
    db.flush()
    material.active_version_id = version.id
    db.commit()
    return material, version


def test_document_page_geometry_round_trips():
    page = DocumentPage(page_no=3, page_width=595.0, page_height=842.0)
    restored = DocumentPage.from_dict(page.to_dict())
    assert (restored.page_width, restored.page_height) == (595.0, 842.0)


def test_material_fts_rebuild_is_stable(db_session, sample_user, sample_course):
    material, version = _material(db_session, sample_user, sample_course)
    chunk = MaterialChunk(
        material_id=material.id,
        material_version_id=version.id,
        course_id=sample_course.id,
        chunk_index=0,
        text="数据链路层可靠传输",
        is_active=1,
        is_indexable=1,
    )
    db_session.add(chunk)
    db_session.commit()

    first = rebuild_material_fts(db_session, material.id)
    second = rebuild_material_fts(db_session, material.id)

    assert first["indexed_count"] == first["indexable_chunk_count"] == 1
    assert second["indexed_count"] == 1
    assert second["changed"] is False


def test_selection_context_is_owned_and_prioritises_same_page(
    db_session, sample_user, sample_course
):
    material, version = _material(db_session, sample_user, sample_course)
    for index, page_no in enumerate((6, 7, 8)):
        db_session.add(MaterialChunk(
            material_id=material.id,
            material_version_id=version.id,
            course_id=sample_course.id,
            chunk_index=index,
            page_no=page_no,
            text=f"page {page_no}",
            is_active=1,
            is_indexable=1,
        ))
    db_session.commit()
    context = {"material_id": material.id, "page_no": 7, "selected_text": "可靠传输", "source_block_ids": []}

    owned = validate_selection_context(db_session, sample_user, sample_course.id, context)
    chunks = _selection_chunks(db_session, owned, context)

    assert chunks[0]["page_no"] == 7
    assert chunks[0]["retrieval_mode"] == "selection_context"

    with pytest.raises(NotFoundException):
        validate_selection_context(
            db_session,
            sample_user,
            sample_course.id,
            {**context, "material_id": material.id + 999},
        )
