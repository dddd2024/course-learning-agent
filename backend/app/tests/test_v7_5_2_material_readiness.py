"""V7.5.2 reader-readiness contract tests."""
from __future__ import annotations

from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.parse_job import ParseJob
from app.services.material_readiness_service import material_readiness


def _material(db_session, sample_course, sample_user, file_type: str = "txt"):
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename=f"notes.{file_type}",
        file_type=file_type,
        file_path=f"material/notes.{file_type}",
        status="ready",
    )
    db_session.add(material)
    db_session.flush()
    version = MaterialVersion(material_id=material.id, version=1, status="ready")
    db_session.add(version)
    db_session.flush()
    material.active_version_id = version.id
    job = ParseJob(material_id=material.id, material_version_id=version.id, user_id=sample_user.id, status="succeeded")
    db_session.add(job)
    db_session.commit()
    return material, version


def _chunk(db_session, material, version, sample_course, *, text="useful text", indexable=1):
    row = MaterialChunk(
        material_id=material.id,
        material_version_id=version.id,
        course_id=sample_course.id,
        chunk_index=0,
        text=text,
        is_active=1,
        is_indexable=indexable,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _index(db_session, chunk_id: int, course_id: int) -> None:
    db_session.execute(
        __import__("sqlalchemy").text(
            "CREATE VIRTUAL TABLE material_chunks_fts USING fts5(chunk_id UNINDEXED, course_id UNINDEXED, body, title)"
        )
    )
    db_session.execute(
        __import__("sqlalchemy").text(
            "INSERT INTO material_chunks_fts(chunk_id, course_id, body, title) VALUES (:id, :course, 'useful text', '')"
        ),
        {"id": chunk_id, "course": course_id},
    )
    db_session.commit()


def test_txt_is_usable_only_after_active_chunk_and_fts(db_session, sample_course, sample_user):
    material, version = _material(db_session, sample_course, sample_user)
    chunk = _chunk(db_session, material, version, sample_course)
    _index(db_session, chunk.id, sample_course.id)

    readiness = material_readiness(db_session, material)

    assert readiness["usable"] is True
    assert readiness["reader_mode"] == "structured_text"
    assert readiness["active_chunk_count"] == readiness["fts_indexed_chunk_count"] == 1


def test_ready_material_without_active_version_is_not_usable(db_session, sample_course, sample_user):
    material, _ = _material(db_session, sample_course, sample_user)
    material.active_version_id = None
    db_session.commit()

    readiness = material_readiness(db_session, material)

    assert readiness["usable"] is False
    assert "active_version_missing" in readiness["blocking_reasons"]


def test_old_version_chunks_do_not_make_current_version_readable(db_session, sample_course, sample_user):
    material, old_version = _material(db_session, sample_course, sample_user)
    _chunk(db_session, material, old_version, sample_course)
    current = MaterialVersion(material_id=material.id, version=2, status="ready")
    db_session.add(current)
    db_session.flush()
    material.active_version_id = current.id
    db_session.add(ParseJob(material_id=material.id, material_version_id=current.id, user_id=sample_user.id, status="succeeded"))
    db_session.commit()

    readiness = material_readiness(db_session, material)

    assert readiness["active_chunk_count"] == 0
    assert "active_chunks_missing" in readiness["blocking_reasons"]


def test_failed_parse_job_is_explicitly_blocking(db_session, sample_course, sample_user):
    material, version = _material(db_session, sample_course, sample_user)
    _chunk(db_session, material, version, sample_course)
    job = db_session.query(ParseJob).filter(ParseJob.material_id == material.id).one()
    job.status, job.error_message = "failed", "parse crashed"
    db_session.commit()

    readiness = material_readiness(db_session, material)

    assert readiness["parse_job_status"] == "failed"
    assert readiness["parse_error"] == "parse crashed"
    assert "parse_job_status:failed" in readiness["blocking_reasons"]


def test_pdf_missing_page_asset_is_not_usable(db_session, sample_course, sample_user, monkeypatch):
    material, version = _material(db_session, sample_course, sample_user, "pdf")
    chunk = _chunk(db_session, material, version, sample_course)
    _index(db_session, chunk.id, sample_course.id)
    monkeypatch.setattr(
        "app.services.material_readiness_service.evaluate_page_asset_coverage",
        lambda *_: {"expected_pages": 2, "missing_page_numbers": [2], "status": "partial"},
    )

    readiness = material_readiness(db_session, material)

    assert readiness["reader_mode"] == "page"
    assert readiness["missing_page_numbers"] == [2]
    assert "page_assets_incomplete" in readiness["blocking_reasons"]


def test_scanned_pdf_with_complete_pages_is_usable_without_chunks(db_session, sample_course, sample_user, monkeypatch):
    material, _ = _material(db_session, sample_course, sample_user, "pdf")
    monkeypatch.setattr(
        "app.services.material_readiness_service.evaluate_page_asset_coverage",
        lambda *_: {"expected_pages": 1, "missing_page_numbers": [], "status": "ready"},
    )

    readiness = material_readiness(db_session, material)

    assert readiness["usable"] is True
    assert readiness["reader_mode"] == "page"
