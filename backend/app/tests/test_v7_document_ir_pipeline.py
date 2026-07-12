"""V7 production parsing regression tests."""
import io
from pathlib import Path

from app.core import database
from app.models.material import Material, MaterialVersion
from app.models.material_page import MaterialPage
from app.retrieval.document_ir import DocumentPage
from app.retrieval.parsers import parse_file
from app.retrieval.semantic_chunker import semantic_chunk_document
from app.services.material_parser import parse_with_retry


def test_parse_file_returns_v7_document_ir_for_markdown(tmp_path: Path):
    path = tmp_path / "network.md"
    path.write_text("# TCP/IP\nHTTP/2 uses I/O.", encoding="utf-8")
    pages = parse_file(str(path), "md")
    assert isinstance(pages[0], DocumentPage)
    assert pages[0].parser_version == "layout-v7"
    assert pages[0].blocks and pages[0].blocks[0].block_id


def test_semantic_chunk_produces_required_provenance(tmp_path: Path):
    path = tmp_path / "network.txt"
    path.write_text("TCP/IP and CSMA/CD are networking concepts.", encoding="utf-8")
    chunks = semantic_chunk_document(parse_file(str(path), "txt"))
    assert chunks
    assert chunks[0]["chunker_version"] == "semantic-v7"
    assert chunks[0]["source_block_ids"]
    assert chunks[0]["page_start"] == chunks[0]["page_end"] == 1


def test_reader_pages_select_only_active_material_version(client, tmp_path, monkeypatch):
    """Historical pages remain stored but never bleed into the active reader."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    client.post("/api/v1/auth/register", json={"username": "alice", "password": "secret123", "email": "alice@example.test"})
    token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "secret123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    course_id = client.post("/api/v1/courses", json={"name": "操作系统"}, headers=headers).json()["id"]
    material_id = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files={"file": ("notes.txt", io.BytesIO(b"source"), "text/plain")},
        headers=headers,
    ).json()["id"]
    db = database.SessionLocal()
    try:
        material = db.get(Material, material_id)
        old = MaterialVersion(material_id=material_id, version=1, status="ready")
        current = MaterialVersion(material_id=material_id, version=2, status="ready")
        db.add_all([old, current])
        db.flush()
        db.add_all([
            MaterialPage(material_id=material_id, material_version_id=old.id, page_no=1, raw_text="old raw", clean_text="old clean"),
            MaterialPage(material_id=material_id, material_version_id=current.id, page_no=1, raw_text="new raw", clean_text="new clean"),
        ])
        material.active_version_id = current.id
        material.status = "ready"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/api/v1/materials/{material_id}/pages", headers=headers)
    assert response.status_code == 200
    assert [row["raw_text"] for row in response.json()["items"]] == ["new raw"]


def test_reparse_preserves_historical_page_version(db_session, sample_user, sample_course, tmp_path, monkeypatch):
    """A successful reparse creates a new active version without deleting pages."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    source = tmp_path / "notes.txt"
    source.write_text("TCP/IP first version", encoding="utf-8")
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="notes.txt",
        file_type="txt",
        file_path="notes.txt",
        status="uploaded",
    )
    db_session.add(material)
    db_session.commit()

    assert parse_with_retry(db_session, material, sample_user.id, sleep_fn=lambda _: None)[0] == "ready"
    source.write_text("HTTP/2 revised version", encoding="utf-8")
    db_session.refresh(material)
    assert parse_with_retry(db_session, material, sample_user.id, sleep_fn=lambda _: None)[0] == "ready"

    versions = db_session.query(MaterialVersion).filter_by(material_id=material.id).order_by(MaterialVersion.version).all()
    pages = db_session.query(MaterialPage).filter_by(material_id=material.id).all()
    assert len(versions) == 2
    assert len(pages) == 2
    assert material.active_version_id == versions[-1].id
    assert {page.material_version_id for page in pages} == {versions[0].id, versions[1].id}


def test_cancelled_parse_never_creates_or_activates_a_version(
    db_session, sample_user, sample_course, tmp_path, monkeypatch
):
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    (tmp_path / "notes.txt").write_text("TCP/IP cancellation test", encoding="utf-8")
    material = Material(
        user_id=sample_user.id, course_id=sample_course.id, filename="notes.txt",
        file_type="txt", file_path="notes.txt", status="uploaded",
    )
    db_session.add(material)
    db_session.commit()

    checks = {"count": 0}
    def cancel_after_source_read() -> bool:
        checks["count"] += 1
        return checks["count"] >= 2

    status, count = parse_with_retry(
        db_session, material, sample_user.id, is_cancelled=cancel_after_source_read
    )

    db_session.refresh(material)
    assert (status, count) == ("cancelled", 0)
    assert material.status == "uploaded"
    assert material.active_version_id is None
    assert db_session.query(MaterialVersion).filter_by(material_id=material.id).count() == 0


def test_clean_reader_mode_does_not_render_page_clean_text_twice():
    source = (Path(__file__).parents[3] / "frontend" / "src" / "views" / "LearnView.vue").read_text(encoding="utf-8")

    assert "v-if=\"readerMode === 'raw'\"" in source
    assert "v-else-if=\"readerMode === 'page'\"" in source
    assert "v-else class=\"doc-chunks\" @mouseup=\"handleSelection\"" in source
