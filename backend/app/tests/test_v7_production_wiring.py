"""Regression checks for the V7 production, rather than helper-only, wiring."""
from __future__ import annotations

import inspect

from app.services import material_parser


def test_real_parse_service_uses_document_ir_semantic_chunker() -> None:
    source = inspect.getsource(material_parser.parse_with_retry)

    assert "pages = parse_fn(" in source
    assert "semantic_chunk_document(" in source
    assert "clean_document_pages" in source
    assert "MaterialPage(" in source
    assert "source_block_ids_json" in source
    assert "chunker_version" in source


def test_real_parse_service_has_no_fixed_window_chunker_dependency() -> None:
    source = inspect.getsource(material_parser)

    assert "from app.retrieval.chunker import build_chunks" not in source
    assert "build_chunks(" not in inspect.getsource(material_parser.parse_with_retry)


def test_learn_view_records_load_evidence_only_after_reader_data_loaded() -> None:
    from pathlib import Path

    source = (Path(__file__).parents[3] / "frontend" / "src" / "views" / "LearnView.vue").read_text(encoding="utf-8")
    assert "await recordTaskEvent(" in source
    assert "chunks.value.length > 0 || materialPages.value.length > 0" in source
    assert "targetLoadRecorded.value = true" in source
