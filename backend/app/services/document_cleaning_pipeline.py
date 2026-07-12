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

    V7.4-02 P1-01/P1-02: Line-level cleaning within blocks.
    Instead of removing entire blocks that match noise lines, this now
    removes individual noise lines from within multi-line blocks,
    preserving the remaining content. This is called exactly once
    per page (no double cleaning).

    Args:
        pages: Raw DocumentPage objects from the parser.

    Returns:
        New DocumentPage objects with noise lines removed from blocks.
    """
    if not pages:
        return []

    page_texts = [page.text for page in pages]
    clean_results = clean_pages(page_texts)

    cleaned_pages: list[DocumentPage] = []
    for page, cleaned in zip(pages, clean_results):
        removed_lines = {
            d["raw_text"].strip()
            for d in cleaned.decisions
            if d.get("decision") == "removed"
        }
        kept_blocks: list[DocumentBlock] = []
        for block in page.blocks:
            block_text = block.text
            if not block_text.strip():
                continue
            # Line-level cleaning: filter out individual noise lines
            if removed_lines:
                lines = block_text.split("\n")
                kept_lines = [
                    line for line in lines
                    if line.strip() not in removed_lines
                ]
                # Only rebuild if we actually removed something
                if len(kept_lines) < len(lines):
                    block_text = "\n".join(kept_lines)
                    if not block_text.strip():
                        continue  # Skip block if all lines were noise
            kept_blocks.append(DocumentBlock(
                block_id=block.block_id,
                page_no=block.page_no,
                block_type=block.block_type,
                reading_order=block.reading_order,
                text=block_text,
                source_kind=block.source_kind,
            ))
        cleaned_pages.append(DocumentPage(
            page_no=page.page_no,
            blocks=kept_blocks,
            page_type=page.page_type,
            parser_version=page.parser_version,
        ))
    return cleaned_pages
