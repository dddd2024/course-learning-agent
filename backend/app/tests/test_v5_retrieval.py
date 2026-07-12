from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.retrieval.search import keyword_search


def test_fts_alias_recalls_tlb_for_fast_table(db_session, sample_user, sample_course):
    material = Material(user_id=sample_user.id, course_id=sample_course.id, filename="os.txt", file_type="txt", file_path="x", status="ready")
    db_session.add(material); db_session.flush()
    db_session.add(MaterialChunk(material_id=material.id, course_id=sample_course.id, chunk_index=0, title="TLB", text="TLB caches page table translations.", keyword_text="TLB caches page table translations.", is_active=1, is_indexable=1))
    db_session.commit()
    result = keyword_search(db_session, sample_course.id, "快表为什么更快")
    assert result and result[0]["chunk_id"] > 0 and result[0]["retrieval_mode"] == "fts_bm25"
