"""Pydantic schemas for material overview (Phase 2 Task C)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class MaterialOverviewResponse(BaseModel):
    """Objective, verifiable overview of a parsed material.

    No quality grade, no A/B/C score, no percentage — only counts,
    ranges, and rule-based warnings the user can verify against the DB.
    """

    material_id: int
    status: str
    chunk_count: int
    page_range: Optional[List[int]] = None  # [min_page, max_page]
    section_count: int = 0
    keywords: List[str] = []
    warnings: List[str] = []
    # Phase 2 Task D: count of security findings (prompt injection)
    security_findings_count: int = 0
