"""V6-60: FTS Incremental Index Maintenance.

Strict TDD: these tests are written first and fail until
``update_fts_index`` and ``remove_from_fts_index`` are implemented in
``app/retrieval/search.py`` and wired into ``material_parser.py``.

The key change is that ``fts_search`` and ``keyword_search`` no longer
call ``rebuild_fts_index`` on every query — the FTS index is maintained
incrementally by ``update_fts_index`` / ``remove_from_fts_index`` called
from the parse pipeline.

Fixtures: ``db_session``, ``sample_user``, ``sample_course`` from
conftest.py.  Material and MaterialChunk rows are created directly.
"""
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.retrieval.search import (
    fts_search,
    keyword_search,
    rebuild_fts_index,
    remove_from_fts_index,
    update_fts_index,
)


def _create_material(db_session, sample_user, sample_course, status="ready"):
    """Create a minimal Material row."""
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="test.txt",
        file_type="txt",
        file_path="test.txt",
        status=status,
    )
    db_session.add(material)
    db_session.flush()
    return material


def _create_chunk(
    db_session,
    sample_course,
    material,
    text,
    title=None,
    chunk_index=0,
    is_active=1,
    is_indexable=1,
):
    """Create a minimal MaterialChunk row."""
    chunk = MaterialChunk(
        material_id=material.id,
        course_id=sample_course.id,
        chunk_index=chunk_index,
        title=title,
        text=text,
        is_active=is_active,
        is_indexable=is_indexable,
        keyword_text=text,
    )
    db_session.add(chunk)
    db_session.flush()
    return chunk


# ---------------------------------------------------------------------------
# update_fts_index — incremental add / replace
# ---------------------------------------------------------------------------


def test_update_fts_index_single_chunk(db_session, sample_user, sample_course):
    """Add one chunk to FTS, verify it's searchable."""
    material = _create_material(db_session, sample_user, sample_course)
    chunk = _create_chunk(
        db_session, sample_course, material,
        "TLB is a cache for page tables",
    )

    update_fts_index(db_session, [chunk.id])

    results = fts_search(db_session, sample_course.id, "TLB")
    assert len(results) >= 1
    assert results[0]["chunk_id"] == chunk.id


def test_update_fts_index_multiple_chunks(db_session, sample_user, sample_course):
    """Add multiple chunks, all searchable."""
    material = _create_material(db_session, sample_user, sample_course)
    chunk1 = _create_chunk(
        db_session, sample_course, material,
        "TCP protocol header structure",
        chunk_index=0,
    )
    chunk2 = _create_chunk(
        db_session, sample_course, material,
        "UDP protocol header structure",
        chunk_index=1,
    )

    update_fts_index(db_session, [chunk1.id, chunk2.id])

    results = fts_search(db_session, sample_course.id, "protocol")
    assert len(results) >= 2
    ids = {r["chunk_id"] for r in results}
    assert chunk1.id in ids
    assert chunk2.id in ids


def test_update_fts_index_replaces_existing(db_session, sample_user, sample_course):
    """Update existing chunk text, verify new text searchable."""
    material = _create_material(db_session, sample_user, sample_course)
    chunk = _create_chunk(
        db_session, sample_course, material,
        "old text about networking protocols",
    )

    update_fts_index(db_session, [chunk.id])

    # Verify old text is searchable
    results = fts_search(db_session, sample_course.id, "networking")
    assert any(r["chunk_id"] == chunk.id for r in results)

    # Update the chunk text
    chunk.text = "new text about database systems"
    db_session.flush()
    update_fts_index(db_session, [chunk.id])

    # Old text should no longer be searchable via FTS for this chunk
    results = fts_search(db_session, sample_course.id, "networking")
    assert all(r["chunk_id"] != chunk.id for r in results)

    # New text should be searchable
    results = fts_search(db_session, sample_course.id, "database")
    assert any(r["chunk_id"] == chunk.id for r in results)


# ---------------------------------------------------------------------------
# remove_from_fts_index — incremental delete
# ---------------------------------------------------------------------------


def test_remove_from_fts_index(db_session, sample_user, sample_course):
    """Remove a chunk from FTS, verify not searchable."""
    material = _create_material(db_session, sample_user, sample_course)
    chunk = _create_chunk(
        db_session, sample_course, material,
        "Cache coherence protocol overview",
    )

    update_fts_index(db_session, [chunk.id])
    results = fts_search(db_session, sample_course.id, "cache")
    assert any(r["chunk_id"] == chunk.id for r in results)

    remove_from_fts_index(db_session, [chunk.id])
    results = fts_search(db_session, sample_course.id, "cache")
    assert all(r["chunk_id"] != chunk.id for r in results)


def test_version_switch_removes_old_active_chunk_from_fts(
    db_session, sample_user, sample_course
):
    """Only the active material version may remain in the retrieval index."""
    material = _create_material(db_session, sample_user, sample_course)
    old = _create_chunk(db_session, sample_course, material, "obsolete TLB definition")
    new = _create_chunk(
        db_session, sample_course, material, "current TCP definition", chunk_index=1, is_active=0
    )
    update_fts_index(db_session, [old.id, new.id])
    old.is_active, new.is_active = 0, 1
    db_session.flush()
    update_fts_index(db_session, [old.id, new.id])

    assert all(row["chunk_id"] != old.id for row in fts_search(db_session, sample_course.id, "TLB"))
    assert any(row["chunk_id"] == new.id for row in fts_search(db_session, sample_course.id, "TCP"))


def test_keyword_search_falls_back_when_fts_is_unavailable(
    db_session, sample_user, sample_course, monkeypatch
):
    material = _create_material(db_session, sample_user, sample_course)
    chunk = _create_chunk(db_session, sample_course, material, "TCP fallback search evidence")
    db_session.commit()
    monkeypatch.setattr("app.retrieval.search._ensure_fts_table", lambda _db: (_ for _ in ()).throw(RuntimeError("FTS unavailable")))

    results = keyword_search(db_session, sample_course.id, "TCP")
    assert any(row["chunk_id"] == chunk.id for row in results)


# ---------------------------------------------------------------------------
# Search works without rebuild_fts_index being called
# ---------------------------------------------------------------------------


def test_fts_search_without_rebuild(db_session, sample_user, sample_course):
    """Search works without rebuild_fts_index being called."""
    material = _create_material(db_session, sample_user, sample_course)
    chunk = _create_chunk(
        db_session, sample_course, material,
        "Virtual memory management in operating systems",
    )

    # Incremental update — NO full rebuild
    update_fts_index(db_session, [chunk.id])

    # fts_search should find the chunk without rebuild_fts_index
    results = fts_search(db_session, sample_course.id, "virtual")
    assert len(results) >= 1
    assert results[0]["chunk_id"] == chunk.id


def test_keyword_search_without_rebuild(db_session, sample_user, sample_course):
    """keyword_search works without rebuild."""
    material = _create_material(db_session, sample_user, sample_course)
    chunk = _create_chunk(
        db_session, sample_course, material,
        "TCP three way handshake establishes connection",
    )

    update_fts_index(db_session, [chunk.id])

    results = keyword_search(db_session, sample_course.id, "TCP")
    assert len(results) >= 1
    assert results[0]["chunk_id"] == chunk.id


# ---------------------------------------------------------------------------
# rebuild_fts_index still works (for migrations / manual rebuilds)
# ---------------------------------------------------------------------------


def test_rebuild_fts_index_still_works(db_session, sample_user, sample_course):
    """Full rebuild still works for migrations."""
    material = _create_material(db_session, sample_user, sample_course)
    _create_chunk(
        db_session, sample_course, material,
        "DNS domain name system resolution",
    )

    # Full rebuild should index all active+indexable chunks
    rebuild_fts_index(db_session)

    results = fts_search(db_session, sample_course.id, "DNS")
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# After parsing, chunks are in FTS without explicit rebuild
# ---------------------------------------------------------------------------


def test_fts_index_after_parse(db_session, sample_user, sample_course, tmp_path, monkeypatch):
    """After material parsing, chunks are in FTS without explicit rebuild."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))

    from app.retrieval.document_ir import DocumentBlock, DocumentPage
    from app.services.material_parser import parse_with_retry

    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="notes.txt",
        file_type="txt",
        file_path="notes.txt",
        status="uploaded",
    )
    db_session.add(material)
    db_session.flush()

    # Create the file so Path(settings.UPLOAD_DIR) / material.file_path exists
    (tmp_path / "notes.txt").write_text(
        "Page cache and TLB translation lookaside buffer "
        "for virtual address translation.",
        encoding="utf-8",
    )

    # Mock parse_fn to return a simple page
    def mock_parse_fn(file_path, file_type):
        return [
                DocumentPage(
                    page_no=1,
                    blocks=[
                        DocumentBlock(
                            block_id="fts-source-1",
                            page_no=1,
                            block_type="body",
                            reading_order=1,
                            text="Page cache and TLB translation lookaside "
                            "buffer for virtual address translation."
                        )
                ],
            )
        ]

    # Avoid LLM calls in quality evaluation
    monkeypatch.setattr(
        "app.services.material_parser.evaluate_chunks_quality",
        lambda chunks: [{"quality": 0.5, "reason": ""} for _ in chunks],
    )

    status, count = parse_with_retry(
        db_session,
        material,
        sample_user.id,
        parse_fn=mock_parse_fn,
        max_retries=1,
    )
    assert status == "ready"
    assert count >= 1

    # FTS should be populated by the parse pipeline — no explicit rebuild
    results = fts_search(db_session, sample_course.id, "TLB")
    assert len(results) >= 1
    assert any("TLB" in r["text"] for r in results)
