"""File parsers that extract text content from uploaded materials.

Each parser returns text in a uniform shape so the chunker can consume
it without knowing the source format:

* ``parse_txt`` / ``parse_docx`` return a single string (no page concept)
* ``parse_pdf`` returns ``[(page_no, text), ...]`` (one entry per page)
* ``parse_file`` dispatches by extension and normalises the output to a
  list of ``(page_no, text)`` tuples where ``page_no`` is ``None`` for
  non-paginated formats.

Errors from the underlying libraries (e.g. ``PdfReadError`` on a corrupt
PDF) propagate to the caller so the parse endpoint can mark the material
as ``failed`` with the exception message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.core.exceptions import BusinessException


@dataclass(frozen=True)
class TextBlock:
    text: str
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    font_size: float | None = None
    block_type: str = "body"
    reading_order: int = 0
    source_kind: str = "text"


@dataclass(frozen=True)
class ParsedPage:
    page_no: int | None
    blocks: list[TextBlock] = field(default_factory=list)
    source_kind: str = "text"
    parser_version: str = "layout-v5"

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks if block.text.strip())

    def __iter__(self):
        """Backward-compatible ``(page_no, text)`` unpacking for callers."""
        yield self.page_no
        yield self.text

    def __getitem__(self, index: int):
        return (self.page_no, self.text)[index]

    def __len__(self) -> int:
        return 2


def parse_txt(file_path: str) -> str:
    """Read a UTF-8 text file and return its contents as a string."""
    with open(file_path, "r", encoding="utf-8") as fh:
        return fh.read()


def parse_pdf(file_path: str) -> List[ParsedPage]:
    """Read a PDF file with pypdf, returning ``[(page_no, text), ...]``.

    Page numbers are 1-indexed so they line up with how a reader would
    cite a page in the source document.
    """
    try:
        import fitz
        document = fitz.open(file_path)
        pages: List[ParsedPage] = []
        for index, page in enumerate(document):
            blocks = []
            for raw in page.get_text("dict").get("blocks", []):
                if raw.get("type") != 0:
                    continue
                text = "".join(span.get("text", "") for line in raw.get("lines", []) for span in line.get("spans", [])).strip()
                if not text:
                    continue
                x0, y0, x1, y1 = raw.get("bbox", (0, 0, 0, 0))
                size = max((float(span.get("size", 0)) for line in raw.get("lines", []) for span in line.get("spans", [])), default=0)
                kind = "title" if size >= 18 or (y0 < 100 and len(text) < 90) else "footer" if y0 > page.rect.height * .88 else "body"
                blocks.append(TextBlock(text, (x0, y0, x1, y1), size, kind, 0, "pdf"))
            blocks = [TextBlock(b.text, b.bbox, b.font_size, b.block_type, order, b.source_kind) for order, b in enumerate(sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0])))]
            pages.append(ParsedPage(index + 1, blocks, "image_only" if not blocks and page.get_images() else "pdf"))
        return pages
    except ImportError:
        from pypdf import PdfReader
        return [ParsedPage(index + 1, [TextBlock(page.extract_text() or "", source_kind="pypdf")], "pdf", "pypdf-legacy") for index, page in enumerate(PdfReader(file_path).pages)]


def parse_docx(file_path: str) -> str:
    """Read a .docx file with python-docx, joining non-empty paragraphs."""
    from docx import Document

    document = Document(file_path)
    paragraphs = [p.text for p in document.paragraphs if p.text]
    return "\n".join(paragraphs)


def parse_md(file_path: str) -> str:
    """Read a Markdown file as UTF-8 text (no structure parsing needed)."""
    with open(file_path, "r", encoding="utf-8") as fh:
        return fh.read()


def parse_pptx(file_path: str) -> List[ParsedPage]:
    """Read a .pptx file with python-pptx, returning ``[(slide_no, text), ...]``.

    Slide numbers are 1-indexed (slide_index + 1). Extracts text from all
    shapes (title, text boxes, tables) on each slide.
    """
    from pptx import Presentation

    prs = Presentation(file_path)
    pages: List[ParsedPage] = []
    for index, slide in enumerate(prs.slides):
        blocks: List[TextBlock] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        kind = "title" if getattr(shape, "is_placeholder", False) and getattr(shape.placeholder_format, "type", None) in {1, 3} else "body"
                        blocks.append(TextBlock(text, (float(shape.left), float(shape.top), float(shape.left + shape.width), float(shape.top + shape.height)), None, kind, 0, "pptx"))
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        text = cell.text
                        if text:
                            blocks.append(TextBlock(text, source_kind="pptx", block_type="table"))
        ordered = [TextBlock(b.text, b.bbox, b.font_size, b.block_type, order, b.source_kind) for order, b in enumerate(sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0])))]
        pages.append(ParsedPage(index + 1, ordered, "image_only" if not ordered and len(slide.shapes) else "pptx"))
    return pages


def parse_file(
    file_path: str, file_type: str
) -> list:
    """Dispatch to the right parser by ``file_type`` (extension).

    Returns a list of ``(page_no, text)`` tuples. For non-paginated
    formats (txt, docx, md) ``page_no`` is ``None`` and the list has a
    single entry. Raises :class:`BusinessException` for unsupported types.
    """
    normalised = (file_type or "").lower().lstrip(".")
    if normalised == "txt":
        return [(None, parse_txt(file_path))]
    if normalised == "pdf":
        return parse_pdf(file_path)
    if normalised == "docx":
        return [(None, parse_docx(file_path))]
    if normalised == "md":
        return [(None, parse_md(file_path))]
    if normalised == "pptx":
        return parse_pptx(file_path)
    raise BusinessException(message=f"不支持的文件类型: {normalised}")
