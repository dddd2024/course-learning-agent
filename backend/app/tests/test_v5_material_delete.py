from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_page import MaterialPage
from app.services.material_delete_service import delete_material

def test_delete_material_removes_page_chunk_and_version_rows(db_session, sample_user, sample_course):
    material = Material(user_id=sample_user.id, course_id=sample_course.id, filename="a.txt", file_type="txt", file_path="missing/a.txt", status="ready")
    db_session.add(material); db_session.flush()
    version = MaterialVersion(material_id=material.id, version=1, status="ready"); db_session.add(version); db_session.flush()
    db_session.add_all([MaterialChunk(material_id=material.id, material_version_id=version.id, course_id=sample_course.id, chunk_index=0, text="evidence"), MaterialPage(material_id=material.id, material_version_id=version.id, page_no=1)])
    db_session.commit(); counts = delete_material(db_session, material)
    assert counts["chunks"] == 1 and db_session.query(MaterialPage).count() == 0 and db_session.query(Material).count() == 0
