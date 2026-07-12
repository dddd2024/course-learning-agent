"""V7.3-01 P0-01: Block-aware cleaning pipeline for Document IR.

Produces cleaned :class:`DocumentPage` objects from raw parser output so
that headers, footers, page numbers, and standalone URLs never enter the
semantic chunker or the FTS index.

The existing :func:`material_cleaner.clean_pages` operates on flat page
text.  This module bridges it to the block-structured Document IR by
matching cleaning decisions to individual blocks and filtering them.
"""
from __future__ import annotations

from app.retrieval.document_ir import DocumentBlock, DocumentPage
from app.services.material_cleaner import clean_pages


def clean_document_pages(
    pages: list[DocumentPage],
) -> list[DocumentPage]:
    """Apply the cleaning pipeline to block-structured Document IR.

    For each page, the flat-page cleaner is run to identify header,
    footer, page-number, URL, and other noise lines.  Blocks whose
    text matches a removed decision are filtered out, and the remaining
    blocks retain their original ``block_id`` for provenance tracking.

    Args:
        pages: Raw DocumentPage objects from the parser.

    Returns:
        New DocumentPage objects with noise blocks removed.  The
        ``page_no`` and surviving ``DocumentBlock`` objects retain their
        original identifiers.
    """
    if not pages:
        return []

    page_texts = [page.text for page in pages]
    clean_results = clean_pages(page_texts)

    cleaned_pages: list[DocumentPage] = []
    for page, cleaned in zip(pages, clean_results):
        removed_texts = {
            d["raw_text"]
            for d in cleaned.decisions
            if d.get("decision") == "removed"
        }
        kept_blocks: list[DocumentBlock] = []
        for block in page.blocks:
            block_text = block.text.strip()
            if block_text and block_text in removed_texts:
                continue
            kept_blocks.append(block)
        cleaned_pages.append(DocumentPage(
            page_no=page.page_no,
            blocks=kept_blocks,
            page_type=page.page_type,
            parser_version=page.parser_version,
        ))
    return cleaned_pages
