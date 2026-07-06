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

from typing import List, Optional, Tuple

from app.core.exceptions import BusinessException


def parse_txt(file_path: str) -> str:
    """Read a UTF-8 text file and return its contents as a string."""
    with open(file_path, "r", encoding="utf-8") as fh:
        return fh.read()


def parse_pdf(file_path: str) -> List[Tuple[int, str]]:
    """Read a PDF file with pypdf, returning ``[(page_no, text), ...]``.

    Page numbers are 1-indexed so they line up with how a reader would
    cite a page in the source document.
    """
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    pages: List[Tuple[int, str]] = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            # Some pages may fail to extract (e.g. scanned images);
            # treat them as empty rather than aborting the whole file.
            text = ""
        pages.append((index + 1, text))
    return pages


def parse_docx(file_path: str) -> str:
    """Read a .docx file with python-docx, joining non-empty paragraphs."""
    from docx import Document

    document = Document(file_path)
    paragraphs = [p.text for p in document.paragraphs if p.text]
    return "\n".join(paragraphs)


def parse_file(
    file_path: str, file_type: str
) -> List[Tuple[Optional[int], str]]:
    """Dispatch to the right parser by ``file_type`` (extension).

    Returns a list of ``(page_no, text)`` tuples. For non-paginated
    formats (txt, docx) ``page_no`` is ``None`` and the list has a single
    entry. Raises :class:`BusinessException` for unsupported types.
    """
    normalised = (file_type or "").lower().lstrip(".")
    if normalised == "txt":
        return [(None, parse_txt(file_path))]
    if normalised == "pdf":
        return parse_pdf(file_path)
    if normalised == "docx":
        return [(None, parse_docx(file_path))]
    raise BusinessException(message=f"不支持的文件类型: {normalised}")
