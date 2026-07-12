"""Document Intermediate Representation (IR) for V6 layout-aware parsing.

The IR decouples the *structure* extracted by parsers (PDF/PPTX/DOCX)
from the *backward-compatible* :class:`~app.retrieval.parsers.ParsedPage`
/ :class:`~app.retrieval.parsers.TextBlock` types.  The semantic chunker
(V6-12) consumes ``DocumentPage`` objects so it can reason about
headings, lists, tables and image anchors without reaching back into
format-specific code.

Key types
---------
* :class:`DocumentBlock`  – a single semantic unit (heading / body / list /
  table cell / image caption) with a deterministic ``block_id``.
* :class:`DocumentPage`   – one page (or slide) holding an ordered list of
  blocks plus optional tables and image anchors.
* :class:`DocumentLine`   – a text line with bbox and font size.
* :class:`DocumentTable`  – a grid of rows (``list[list[str]]``).
* :class:`DocumentImageAnchor` – records where an image/diagram sits on a
  page so the chunker can avoid splitting through it.

Serialization
-------------
Every dataclass provides ``to_dict()`` / ``from_dict()`` so pages can be
stored as JSON (e.g. in ``material_pages.blocks_json``).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Leaf types
# ---------------------------------------------------------------------------

@dataclass
class DocumentLine:
    """A single text line with bounding box and font size."""

    text: str
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    font_size: Optional[float] = None

    def to_dict(self) -> dict:
        return {"text": self.text, "bbox": list(self.bbox), "font_size": self.font_size}

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentLine":
        return cls(
            text=d["text"],
            bbox=tuple(d.get("bbox", (0, 0, 0, 0))),
            font_size=d.get("font_size"),
        )


@dataclass
class DocumentTable:
    """A table represented as a list of rows (each row is a list of cells)."""

    rows: List[List[str]] = field(default_factory=list)
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)

    def to_dict(self) -> dict:
        return {"rows": self.rows, "bbox": list(self.bbox)}

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentTable":
        return cls(
            rows=d.get("rows", []),
            bbox=tuple(d.get("bbox", (0, 0, 0, 0))),
        )


@dataclass
class DocumentImageAnchor:
    """Records the position of an image or vector diagram on a page."""

    page_no: int
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    label: str = ""
    is_decorative: bool = False

    def to_dict(self) -> dict:
        return {
            "page_no": self.page_no,
            "bbox": list(self.bbox),
            "label": self.label,
            "is_decorative": self.is_decorative,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentImageAnchor":
        return cls(
            page_no=d["page_no"],
            bbox=tuple(d.get("bbox", (0, 0, 0, 0))),
            label=d.get("label", ""),
            is_decorative=d.get("is_decorative", False),
        )


# ---------------------------------------------------------------------------
# DocumentBlock
# ---------------------------------------------------------------------------

def _compute_block_id(page_no: int, reading_order: int, text: str) -> str:
    """Stable, deterministic hash of ``page_no + reading_order + text[:50]``."""
    raw = f"{page_no}:{reading_order}:{text[:50]}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class DocumentBlock:
    """A single semantic block within a document page.

    ``block_id`` is a deterministic 16-char hex digest of
    ``page_no + reading_order + text[:50]`` so the same source always
    produces the same id (useful for provenance tracking across re-parses).
    """

    block_id: str
    page_no: int
    block_type: str  # heading / body / footer / table / list / image_caption
    reading_order: int
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    text: str = ""
    font_size: Optional[float] = None
    list_level: int = 0
    source_kind: str = "text"

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "page_no": self.page_no,
            "block_type": self.block_type,
            "reading_order": self.reading_order,
            "bbox": list(self.bbox),
            "text": self.text,
            "font_size": self.font_size,
            "list_level": self.list_level,
            "source_kind": self.source_kind,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentBlock":
        return cls(
            block_id=d["block_id"],
            page_no=d["page_no"],
            block_type=d["block_type"],
            reading_order=d["reading_order"],
            bbox=tuple(d.get("bbox", (0, 0, 0, 0))),
            text=d.get("text", ""),
            font_size=d.get("font_size"),
            list_level=d.get("list_level", 0),
            source_kind=d.get("source_kind", "text"),
        )


# ---------------------------------------------------------------------------
# DocumentPage
# ---------------------------------------------------------------------------

@dataclass
class DocumentPage:
    """One page (or slide) of a parsed document.

    ``page_type`` is one of ``text`` / ``image_only`` / ``mixed``:
    * ``text``       – mostly text blocks, no significant images.
    * ``image_only`` – only image anchors / captions, no substantive text.
    * ``mixed``      – both text and images present.
    """

    page_no: int
    page_type: str = "text"
    blocks: List[DocumentBlock] = field(default_factory=list)
    tables: List[DocumentTable] = field(default_factory=list)
    images: List[DocumentImageAnchor] = field(default_factory=list)
    parser_version: str = "layout-v6"

    def to_dict(self) -> dict:
        return {
            "page_no": self.page_no,
            "page_type": self.page_type,
            "blocks": [b.to_dict() for b in self.blocks],
            "tables": [t.to_dict() for t in self.tables],
            "images": [a.to_dict() for a in self.images],
            "parser_version": self.parser_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentPage":
        return cls(
            page_no=d["page_no"],
            page_type=d.get("page_type", "text"),
            blocks=[DocumentBlock.from_dict(b) for b in d.get("blocks", [])],
            tables=[DocumentTable.from_dict(t) for t in d.get("tables", [])],
            images=[DocumentImageAnchor.from_dict(a) for a in d.get("images", [])],
            parser_version=d.get("parser_version", "layout-v6"),
        )


# ---------------------------------------------------------------------------
# Conversion from ParsedPage -> DocumentPage
# ---------------------------------------------------------------------------

# Map TextBlock.block_type values to DocumentBlock.block_type values.
_BLOCK_TYPE_MAP = {
    "title": "heading",
    "heading": "heading",
    "body": "body",
    "footer": "footer",
    "table": "table",
    "list": "list",
    "image_caption": "image_caption",
}


def to_document_page(parsed_page: Any) -> DocumentPage:
    """Convert a :class:`ParsedPage` (or duck-typed equivalent) to a
    :class:`DocumentPage`.

    ``parsed_page`` must expose ``page_no``, ``blocks`` (iterable of
    objects with ``text``, ``bbox``, ``font_size``, ``block_type``,
    ``reading_order``, ``source_kind``), ``source_kind``, and
    ``parser_version``.  Optional ``images`` (list of bbox tuples or
    dicts) and ``page_height`` are used for image anchors and page-type
    detection.
    """
    page_no = parsed_page.page_no or 1
    raw_blocks = list(parsed_page.blocks)

    doc_blocks: List[DocumentBlock] = []
    for tb in raw_blocks:
        bt = _BLOCK_TYPE_MAP.get(tb.block_type, tb.block_type)
        doc_blocks.append(
            DocumentBlock(
                block_id=_compute_block_id(page_no, tb.reading_order, tb.text),
                page_no=page_no,
                block_type=bt,
                reading_order=tb.reading_order,
                bbox=tb.bbox,
                text=tb.text,
                font_size=tb.font_size,
                list_level=getattr(tb, "list_level", 0) or 0,
                source_kind=tb.source_kind,
            )
        )

    # Collect image anchors (carried by the parser as ``images``).
    images: List[DocumentImageAnchor] = []
    for img in getattr(parsed_page, "images", None) or []:
        if isinstance(img, dict):
            images.append(DocumentImageAnchor(
                page_no=page_no,
                bbox=tuple(img.get("bbox", (0, 0, 0, 0))),
                label=img.get("label", ""),
                is_decorative=img.get("is_decorative", False),
            ))
        elif isinstance(img, (tuple, list)) and len(img) >= 4:
            images.append(DocumentImageAnchor(
                page_no=page_no,
                bbox=tuple(img[:4]),
            ))

    # Determine page_type: respect the parser's own classification first.
    source_kind = getattr(parsed_page, "source_kind", "text")
    if source_kind == "image_only":
        page_type = "image_only"
    else:
        page_type = _detect_page_type(doc_blocks, images)

    return DocumentPage(
        page_no=page_no,
        page_type=page_type,
        blocks=doc_blocks,
        images=images,
        parser_version="layout-v6",
    )


def to_document_pages(parsed_pages: Sequence[Any]) -> List[DocumentPage]:
    """Convert a sequence of :class:`ParsedPage` to :class:`DocumentPage`."""
    return [to_document_page(p) for p in parsed_pages]


# ---------------------------------------------------------------------------
# Page-type detection
# ---------------------------------------------------------------------------

def _detect_page_type(
    blocks: List[DocumentBlock], images: List[DocumentImageAnchor]
) -> str:
    """Classify a page as ``text`` / ``image_only`` / ``mixed``.

    * ``image_only`` – no heading or body blocks (only captions / images).
    * ``mixed``      – has both substantive text and image anchors.
    * ``text``       – has text but no images.
    """
    has_text = any(
        b.block_type in ("heading", "body", "list", "table") and b.text.strip()
        for b in blocks
    )
    has_images = len(images) > 0
    if not has_text and (has_images or blocks):
        return "image_only"
    if has_text and has_images:
        return "mixed"
    return "text"
