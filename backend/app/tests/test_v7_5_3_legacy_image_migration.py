from __future__ import annotations

from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.services.material_image_migration_service import migrate_legacy_images


def _material(db, user_id: int, course_id: int, name: str) -> Material:
    material = Material(
        user_id=user_id,
        course_id=course_id,
        filename=f"{name}.pdf",
        file_type="pdf",
        file_path=f"{name}.pdf",
        status="ready",
    )
    db.add(material)
    db.flush()
    return material


def _version(db, material: Material, number: int) -> MaterialVersion:
    version = MaterialVersion(material_id=material.id, version=number, status="ready")
    db.add(version)
    db.flush()
    return version


def _image(db, material: Material, course_id: int, *, chunk_id=None) -> MaterialImage:
    image = MaterialImage(
        material_id=material.id,
        material_version_id=None,
        course_id=course_id,
        chunk_id=chunk_id,
        page_no=1,
        image_filename="legacy.png",
        image_path=f"legacy/{material.id}.png",
        width=10,
        height=10,
        format="png",
        render_status="ready",
    )
    db.add(image)
    db.flush()
    return image


def test_migration_binds_from_referenced_chunk(
    db_session, sample_user, sample_course,
):
    material = _material(db_session, sample_user.id, sample_course.id, "chunk-bound")
    _version(db_session, material, 1)
    v2 = _version(db_session, material, 2)
    chunk = MaterialChunk(
        material_id=material.id,
        material_version_id=v2.id,
        course_id=sample_course.id,
        chunk_index=0,
        page_no=1,
        page_start=1,
        page_end=1,
        text="v2",
        raw_text="v2",
        content_hash="a" * 64,
        is_active=1,
    )
    db_session.add(chunk)
    db_session.flush()
    image = _image(db_session, material, sample_course.id, chunk_id=chunk.id)

    result = migrate_legacy_images(db_session)

    db_session.refresh(image)
    assert image.material_version_id == v2.id
    assert image.render_status == "ready"
    assert result["bound_from_chunk"] == 1
    assert result["remaining_null_ready"] == 0


def test_migration_binds_single_version_page_image(
    db_session, sample_user, sample_course,
):
    material = _material(db_session, sample_user.id, sample_course.id, "single-version")
    version = _version(db_session, material, 1)
    image = _image(db_session, material, sample_course.id)

    result = migrate_legacy_images(db_session)

    db_session.refresh(image)
    assert image.material_version_id == version.id
    assert result["bound_single_version"] == 1
    assert result["remaining_null_ready"] == 0


def test_migration_quarantines_ambiguous_image(
    db_session, sample_user, sample_course,
):
    material = _material(db_session, sample_user.id, sample_course.id, "ambiguous")
    _version(db_session, material, 1)
    _version(db_session, material, 2)
    image = _image(db_session, material, sample_course.id)

    result = migrate_legacy_images(db_session)

    db_session.refresh(image)
    assert image.material_version_id is None
    assert image.render_status == "quarantined"
    assert image.error_code == "LEGACY_IMAGE_VERSION_AMBIGUOUS"
    assert result["quarantined"] == 1
    assert result["remaining_null_ready"] == 0


def test_migration_is_idempotent(
    db_session, sample_user, sample_course,
):
    material = _material(db_session, sample_user.id, sample_course.id, "idempotent")
    version = _version(db_session, material, 1)
    image = _image(db_session, material, sample_course.id)

    first = migrate_legacy_images(db_session)
    second = migrate_legacy_images(db_session)

    db_session.refresh(image)
    assert image.material_version_id == version.id
    assert first["bound_single_version"] == 1
    assert second["bound_single_version"] == 0
    assert second["quarantined"] == 0
