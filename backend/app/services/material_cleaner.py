"""The single, auditable cleaning pipeline for reader and retrieval text."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_PAGE_NUMBER = re.compile(r"^(?:page\s*)?\d{1,4}$", re.I)
_LABEL = re.compile(r"^(?:图|表|figure|animation)\s*\d+[.:：]?$", re.I)
_URL = re.compile(r"^(?:https?://|www\.)\S+$", re.I)
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
