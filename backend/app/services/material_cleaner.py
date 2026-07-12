"""The single, auditable cleaning pipeline for reader and retrieval text."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy.orm import Session


_PAGE_NUMBER = re.compile(r"^(?:page\s*)?\d{1,4}$", re.I)
_CN_PAGE_NUMBER = re.compile(r"^第\s*\d+\s*页$")
_LABEL = re.compile(r"^(?:图|表|figure|animation)\s*\d+[.:：]?$", re.I)
# Only match actual URLs (http://, https://, ftp://, www.), not lines
# that merely contain a forward slash.  This preserves technical terms
# such as TCP/IP, CSMA/CD, HTTP/2, and I/O.
_URL = re.compile(r"^(?:https?://|ftp://|www\.)\S+$", re.I)
_COURSE_LABEL = re.compile(r"^(?:课程学院|教材版本|主讲教师|教师)\s*[:：]", re.I)


@dataclass(frozen=True)
class CleanPage:
    text: str
    decisions: list[dict]


def clean_pages(page_texts: Iterable[str]) -> list[CleanPage]:
    """Clean layout text once and retain an explainable decision for every line.

    Repeated first/last lines across pages are treated as header/footer only
    when they occur on more than one page.  This prevents ordinary short
    content (for example ``TCP/IP``) from being silently removed.
    """
    lines_per_page = [[line.strip() for line in (text or "").splitlines() if line.strip()] for text in page_texts]
    edge_counts: dict[str, int] = {}
    for lines in lines_per_page:
        for line in set(lines[:1] + lines[-1:]):
            edge_counts[line] = edge_counts.get(line, 0) + 1

    result: list[CleanPage] = []
    for lines in lines_per_page:
        kept: list[str] = []
        decisions: list[dict] = []
        for line in lines:
            reason = None
            if edge_counts.get(line, 0) > 1 and (line == lines[0] or line == lines[-1]):
                reason = "repeated_header_footer"
            elif _PAGE_NUMBER.fullmatch(line):
                reason = "isolated_page_number"
            elif _CN_PAGE_NUMBER.fullmatch(line):
                reason = "isolated_page_number"
            elif _COURSE_LABEL.match(line):
                reason = "course_label"
            elif _URL.fullmatch(line):
                reason = "standalone_url"
            elif _LABEL.fullmatch(line):
                reason = "graphic_or_animation_label"
            if reason:
                decisions.append({"raw_text": line, "decision": "removed", "reason": reason})
            elif kept and kept[-1] == line:
                decisions.append({"raw_text": line, "decision": "merged", "reason": "adjacent_duplicate"})
            else:
                kept.append(line)
                decisions.append({"raw_text": line, "decision": "kept", "reason": "semantic_content"})
        result.append(CleanPage("\n".join(kept), decisions))
    return result


def get_cleaning_decisions(page: CleanPage) -> list[dict]:
    """Return the cleaning decisions for a page in a user-friendly format.

    Transforms the internal decision representation into a list of dicts
    with the following keys:

    - ``original_line``: the text before cleaning.
    - ``action``: one of ``kept``, ``removed``, ``merged``.
    - ``reason``: the decision type (e.g. ``standalone_url``,
      ``isolated_page_number``, ``semantic_content``).
    - ``cleaned_line``: the text after cleaning, or ``None`` if the line
      was removed or merged into a previous line.
    """
    result: list[dict] = []
    for d in page.decisions:
        action = d.get("decision", "kept")
        original = d.get("raw_text", "")
        reason = d.get("reason", "")
        if action == "kept":
            cleaned_line: str | None = original
        else:
            cleaned_line = None
        result.append({
            "original_line": original,
            "action": action,
            "reason": reason,
            "cleaned_line": cleaned_line,
        })
    return result


def get_raw_pages(material_id: int, db: Session) -> list[dict]:
    """Return the raw (uncleaned) page text for a material.

    Queries the ``material_pages`` table and returns a list of dicts
    with ``page_no`` and ``text`` (the ``raw_text`` column), ordered
    by page number.  This provides the "original mode" view where the
    user can see text exactly as extracted before cleaning.
    """
    from app.models.material_page import MaterialPage

    from app.models.material import Material
    material = db.get(Material, material_id)
    query = db.query(MaterialPage).filter(MaterialPage.material_id == material_id)
    if material and material.active_version_id is not None:
        query = query.filter(MaterialPage.material_version_id == material.active_version_id)
    rows = (
        query
        .order_by(MaterialPage.page_no.asc())
        .all()
    )
    return [
        {"page_no": r.page_no, "text": r.raw_text or ""}
        for r in rows
    ]


def get_clean_pages(material_id: int, db: Session) -> list[dict]:
    """Return the cleaned page text for a material.

    Queries the ``material_pages`` table and returns a list of dicts
    with ``page_no`` and ``text`` (the ``clean_text`` column), ordered
    by page number.  This is the text used for retrieval and display
    after noise (URLs, page numbers, headers/footers) has been removed.
    """
    from app.models.material_page import MaterialPage

    from app.models.material import Material
    material = db.get(Material, material_id)
    query = db.query(MaterialPage).filter(MaterialPage.material_id == material_id)
    if material and material.active_version_id is not None:
        query = query.filter(MaterialPage.material_version_id == material.active_version_id)
    rows = (
        query
        .order_by(MaterialPage.page_no.asc())
        .all()
    )
    return [
        {"page_no": r.page_no, "text": r.clean_text or ""}
        for r in rows
    ]
