"""Conservative visual-layout annotations for PDF text blocks."""
from __future__ import annotations

from app.retrieval.document_ir import DocumentPage


def annotate_pdf_layout(pages: list[DocumentPage]) -> list[DocumentPage]:
    """Mark diagram-like pages without inventing a linear reading order.

    A high count of tiny, spatially dispersed text blocks is a strong signal
    for SmartArt/network diagrams exported from slides.  Those pages remain
    searchable by page, but their visual asset is the primary reader source.
    """
    for page in pages:
        blocks = [block for block in page.blocks if block.text.strip()]
        if not blocks:
            continue
        short = [block for block in blocks if len(block.text.strip()) <= 30]
        xs = {round(block.bbox[0] / 40) for block in short}
        ys = {round(block.bbox[1] / 40) for block in short}
        diagram_like = (
            page.page_type in {"pdf", "mixed"}
            and len(short) >= 8
            and len(short) / len(blocks) >= 0.7
            and len(xs) >= 3
            and len(ys) >= 2
        )
        if diagram_like:
            page.layout_uncertain = True
            for block in blocks:
                block.visual_role = "diagram_label"
                block.reading_order_confidence = 0.35
    return pages
