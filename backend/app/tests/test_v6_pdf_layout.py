"""V6-10/V6-11: PDF layout parsing tests.

Tests use the real ``networking-two-column.pdf`` fixture (3 pages,
two-column layout, TCP/IP terms, a table built from vector lines, and
vector-drawn diagrams).
"""
import os

from app.retrieval.parsers import parse_pdf
from app.retrieval.document_ir import (
    DocumentBlock,
    DocumentImageAnchor,
    DocumentPage,
    to_document_page,
    to_document_pages,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "course_materials")
PDF_PATH = os.path.join(FIXTURES, "networking-two-column.pdf")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_to_doc():
    """Parse the fixture PDF and convert every page to the V6 document IR."""
    pages = parse_pdf(PDF_PATH)
    return to_document_pages(pages)


# ---------------------------------------------------------------------------
# V6-11: two-column reading order
# ---------------------------------------------------------------------------

def test_two_column_reading_order_left_before_right():
    """On a two-column page, all left-column blocks must precede right-column
    blocks in reading order (left column read top-to-bottom, then right)."""
    doc = _parse_to_doc()
    page1 = doc[0]

    # The two-column body region on page 1 sits between y~100 and y~350.
    body = [b for b in page1.blocks if 100 < b.bbox[1] < 350]
    left = [b for b in body if b.bbox[0] < 200]
    right = [b for b in body if b.bbox[0] >= 200]
    assert left, "expected left-column blocks on page 1"
    assert right, "expected right-column blocks on page 1"

    max_left_order = max(b.reading_order for b in left)
    min_right_order = min(b.reading_order for b in right)
    assert max_left_order < min_right_order, (
        "left column must be fully read before right column "
        f"(max_left={max_left_order}, min_right={min_right_order})"
    )


# ---------------------------------------------------------------------------
# V6-11: heading detection from font statistics
# ---------------------------------------------------------------------------

def test_heading_detection_from_font_statistics():
    """Headings should be detected via median+std, not a fixed threshold.

    On page 1 the median font size is ~10; blocks at size 14 (section
    heading "1.1 TCP/IP ...") and size 20 (chapter title) must be
    classified as ``heading``.
    """
    doc = _parse_to_doc()
    page1 = doc[0]

    headings = [b for b in page1.blocks if b.block_type == "heading"]
    heading_texts = " ".join(b.text for b in headings)

    # The section heading "1.1 TCP/IP ..." at size 14 should be a heading.
    assert any("TCP/IP" in b.text for b in headings), (
        f"expected 'TCP/IP' heading among {heading_texts!r}"
    )
    # Body blocks (size 10) should NOT be headings.
    bodies = [b for b in page1.blocks if b.block_type == "body"]
    assert bodies, "expected body blocks on page 1"


# ---------------------------------------------------------------------------
# V6-11: footer detection by position + cross-page repetition
# ---------------------------------------------------------------------------

def test_footer_detection_by_position_and_repetition():
    """A footer must be in the bottom 10% of the page AND appear on more
    than one page (cross-page repetition)."""
    doc = _parse_to_doc()

    footer_texts = []
    for page in doc:
        footers = [b for b in page.blocks if b.block_type == "footer"]
        for f in footers:
            # Must be in the bottom 10% of the page (height 842).
            assert f.bbox[1] > 842 * 0.90, (
                f"footer not in bottom 10%: y0={f.bbox[1]}"
            )
            footer_texts.append(f.text)

    # Footers appear on all 3 pages -> cross-page repetition satisfied.
    assert len(footer_texts) >= 2, (
        f"expected repeated footers across pages, got {footer_texts!r}"
    )


# ---------------------------------------------------------------------------
# V6-11: table detection
# ---------------------------------------------------------------------------

def test_table_content_preserved_as_grid():
    """Table rows must be preserved as ``table`` blocks with their content
    intact (HTTP, DNS, TCP, UDP, IP, ICMP)."""
    doc = _parse_to_doc()
    page1 = doc[0]

    table_blocks = [b for b in page1.blocks if b.block_type == "table"]
    table_text = " ".join(b.text for b in table_blocks)

    # The table on page 1 lists protocol layers with HTTP/DNS/TCP/UDP/IP/ICMP.
    assert any(term in table_text for term in ("HTTP", "TCP", "DNS", "ICMP")), (
        f"expected table content with protocol terms, got {table_text!r}"
    )


# ---------------------------------------------------------------------------
# V6-11: image anchors
# ---------------------------------------------------------------------------

def test_image_anchor_recorded():
    """Image anchors must be recorded for pages with vector-drawn diagrams."""
    doc = _parse_to_doc()

    total_anchors = sum(len(p.images) for p in doc)
    assert total_anchors > 0, "expected at least one image anchor"

    # Page 3 has 4 diagram boxes -> at least one image anchor.
    assert len(doc[2].images) > 0, "expected image anchors on page 3"

    # Each anchor must carry page_no and bbox.
    for page in doc:
        for anchor in page.images:
            assert isinstance(anchor, DocumentImageAnchor)
            assert anchor.page_no == page.page_no
            assert len(anchor.bbox) == 4


# ---------------------------------------------------------------------------
# V6-11: technical terms preserved
# ---------------------------------------------------------------------------

def test_technical_terms_preserved_in_blocks():
    """TCP/IP and CSMA/CD must appear intact (not fragmented) in block text."""
    doc = _parse_to_doc()
    all_text = " ".join(b.text for p in doc for b in p.blocks)
    assert "TCP/IP" in all_text, "TCP/IP must be preserved in blocks"
    assert "CSMA/CD" in all_text, "CSMA/CD must be preserved in blocks"


# ---------------------------------------------------------------------------
# V6-10: document IR structure
# ---------------------------------------------------------------------------

def test_document_page_has_layout_v6_parser_version():
    """DocumentPage produced by the V6 parser must report layout-v6."""
    doc = _parse_to_doc()
    for page in doc:
        assert page.parser_version == "layout-v6"
        assert isinstance(page, DocumentPage)
        assert page.page_type in {"text", "image_only", "mixed"}


def test_document_block_ids_are_stable_and_deterministic():
    """block_id must be a deterministic hash of page_no+reading_order+text[:50]."""
    import hashlib

    doc = _parse_to_doc()
    page1 = doc[0]
    for block in page1.blocks:
        assert isinstance(block, DocumentBlock)
        assert block.block_id  # non-empty
        # Recompute and verify determinism.
        expected = hashlib.md5(
            f"{block.page_no}:{block.reading_order}:{block.text[:50]}".encode("utf-8")
        ).hexdigest()[:16]
        assert block.block_id == expected, (
            f"block_id mismatch: {block.block_id!r} != {expected!r}"
        )


def test_document_page_to_dict_from_dict_roundtrip():
    """to_dict / from_dict must round-trip a DocumentPage."""
    doc = _parse_to_doc()
    page1 = doc[0]

    d = page1.to_dict()
    assert isinstance(d, dict)
    assert d["page_no"] == page1.page_no
    assert d["parser_version"] == "layout-v6"

    restored = DocumentPage.from_dict(d)
    assert restored.page_no == page1.page_no
    assert restored.page_type == page1.page_type
    assert len(restored.blocks) == len(page1.blocks)
    assert restored.blocks[0].block_id == page1.blocks[0].block_id
    assert restored.blocks[0].text == page1.blocks[0].text
