"""OutlineAgent — extracts structured knowledge points from course materials.

The agent:
1. Loads the ``outline`` prompt template and fills the ``{course_name}``
   and ``{retrieved_chunks}`` placeholders.
2. Calls ``call_llm`` with ``agent_type="outline"`` to get a structured
   JSON response with a ``knowledge_points`` list.
3. Reconciles each knowledge point's ``source_chunk_ids`` against the
   actual chunk ids passed in (the mock LLM returns placeholder strings
   like ``"chunk_1"``; the real LLM may return ids that need validating).
4. Computes the final ``importance`` by combining the LLM-given base
   score with rule-based adjustments (title keywords, cross-material
   occurrence) per the design doc §12.2.
5. Returns a list of dicts ready for persistence / API response.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agents.llm import call_llm
from app.agents.prompt_loader import load_prompt
from app.models.course import Course
from app.models.material import Material
from app.models.material_chunk import MaterialChunk

# Keywords that signal a knowledge point is likely exam-relevant.
_IMPORTANCE_KEYWORDS = ("重点", "考试", "例题")

_REQUIRED_FIELDS = (
    "title",
    "summary",
    "importance",
    "source_chunk_ids",
    "exam_style",
    "review_action",
)


def _format_chunks(chunks: list[dict]) -> str:
    """Render chunks into a readable prompt section."""
    if not chunks:
        return "（未检索到相关资料片段）"
    lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        page = chunk.get("page_no")
        page_str = f"，页码 {page}" if page is not None else ""
        lines.append(
            f"[片段{i}] chunk_id={chunk.get('chunk_id')}{page_str}\n"
            f"{chunk.get('text', '')}"
        )
    return "\n\n".join(lines)


def calculate_importance(
    llm_importance: int,
    title: str,
    source_chunk_ids: list,
    chunks: list[dict],
) -> int:
    """Compute the final importance (1-5) from the LLM score + rule bonuses.

    Per design doc §12.2, importance is::

        min(5, llm_importance
              + (1 if title contains 重点/考试/例题 else 0)
              + (1 if appears in >=2 different materials else 0))

    The ``weak_point_error_count`` term is omitted in this initial version
    because weak-point data is not yet available.
    """
    importance = llm_importance

    # Title-keyword bonus.
    if any(kw in (title or "") for kw in _IMPORTANCE_KEYWORDS):
        importance += 1

    # Cross-material bonus: a point sourced from chunks in >=2 materials
    # is likely more central to the course.
    chunk_material_map = {
        c.get("chunk_id"): c.get("material_id") for c in chunks
    }
    material_ids: set = set()
    for cid in source_chunk_ids or []:
        mid = chunk_material_map.get(cid)
        if mid is not None:
            material_ids.add(mid)
    if len(material_ids) >= 2:
        importance += 1

    return min(5, max(1, importance))


def _reconcile_chunk_ids(
    raw_ids: list, valid_ids: list
) -> list:
    """Keep only source_chunk_ids that exist in ``valid_ids``.

    Falls back to all ``valid_ids`` when none match (e.g. the mock LLM
    returns placeholder strings like ``"chunk_1"``).
    """
    valid_set = set(valid_ids)
    matched = [cid for cid in (raw_ids or []) if cid in valid_set]
    if matched:
        return matched
    return list(valid_ids)


def _fetch_chunks(db: Session, course_id: int) -> list[dict]:
    """Load all ready-material chunks for a course as agent input dicts."""
    rows = (
        db.query(MaterialChunk)
        .join(Material, Material.id == MaterialChunk.material_id)
        .filter(
            MaterialChunk.course_id == course_id,
            Material.status == "ready",
        )
        .order_by(MaterialChunk.chunk_index.asc())
        .all()
    )
    return [
        {
            "chunk_id": c.id,
            "text": c.text,
            "material_id": c.material_id,
            "title": c.title,
            "page_no": c.page_no,
        }
        for c in rows
    ]


def generate(
    db: Session,
    course_id: int,
    course_name: str | None = None,
    chunks: list[dict] | None = None,
    user_config: dict | None = None,
) -> list[dict]:
    """Extract structured knowledge points for a course.

    Args:
        db: SQLAlchemy session.
        course_id: Course to extract points for.
        course_name: Display name of the course. Fetched from DB if None.
        chunks: Pre-fetched chunk dicts. Loaded from DB if None.
        user_config: Optional per-user LLM config dict. When supplied,
            it is forwarded to :func:`call_llm` so the call uses the
            user's enabled provider config.

    Returns:
        A list of dicts, each with ``title``, ``summary``,
        ``importance``, ``source_chunk_ids``, ``exam_style``,
        ``review_action``.
    """
    if course_name is None:
        course = (
            db.query(Course).filter(Course.id == course_id).first()
        )
        course_name = course.name if course else ""
    if chunks is None:
        chunks = _fetch_chunks(db, course_id)

    template = load_prompt("outline")
    prompt = template.format(
        course_name=course_name,
        retrieved_chunks=_format_chunks(chunks),
    )

    output = call_llm(
        prompt, agent_type="outline", user_config=user_config
    )
    raw_points = output.get("knowledge_points", [])

    valid_chunk_ids = [c["chunk_id"] for c in chunks]

    results: list[dict[str, Any]] = []
    for point in raw_points:
        source_ids = _reconcile_chunk_ids(
            point.get("source_chunk_ids", []), valid_chunk_ids
        )
        llm_importance = point.get("importance", 3)
        try:
            llm_importance = int(llm_importance)
        except (TypeError, ValueError):
            llm_importance = 3
        importance = calculate_importance(
            llm_importance,
            point.get("title", ""),
            source_ids,
            chunks,
        )
        results.append(
            {
                "title": point.get("title", ""),
                "summary": point.get("summary", ""),
                "importance": importance,
                "source_chunk_ids": source_ids,
                "exam_style": point.get("exam_style", ""),
                "review_action": point.get("review_action", ""),
            }
        )
    return results


__all__ = ["generate", "calculate_importance"]
