"""CourseQAAgent — answers a student question grounded in retrieved chunks.

The agent:
1. Loads the ``course_qa`` prompt template and fills the
   ``{question}`` / ``{course_name}`` / ``{retrieved_chunks}`` placeholders.
2. Calls ``call_llm`` with ``agent_type="course_qa"`` to get a structured
   JSON answer.
3. Validates that the output contains all required fields
   (``answer`` / ``key_points`` / ``citations`` / ``not_found`` /
   ``follow_up_questions``).
4. Runs :func:`verify_citations` to drop any citation whose ``chunk_id``
   is not present in the retrieved chunks (prevents the LLM from
   fabricating references).
5. When no citations survive verification but retrieved chunks exist,
   a fallback citation is synthesised from the top-ranked chunk so the
   response still carries a traceable reference.
"""
from __future__ import annotations

from typing import Any

from app.agents.llm import call_llm_with_meta
from app.agents.prompt_loader import load_prompt
from app.services.security_scanner import PROMPT_GUARD


_REQUIRED_FIELDS = (
    "answer",
    "key_points",
    "citations",
    "not_found",
    "follow_up_questions",
)


def _format_chunks(retrieved_chunks: list[dict]) -> str:
    """Render retrieved chunks into a readable prompt section."""
    if not retrieved_chunks:
        return "（未检索到相关资料片段）"
    lines: list[str] = []
    for i, chunk in enumerate(retrieved_chunks, start=1):
        page = chunk.get("page_no")
        page_str = f"，页码 {page}" if page is not None else ""
        lines.append(
            f"[片段{i}] chunk_id={chunk.get('chunk_id')}{page_str}\n"
            f"{chunk.get('text', '')}"
        )
    return "\n\n".join(lines)


_DEFAULTS = {
    "key_points": list,
    "citations": list,
    "not_found": lambda: False,
    "follow_up_questions": list,
}


def _ensure_fields(output: dict[str, Any]) -> None:
    """Fill in any missing required fields with sensible defaults.

    Real LLMs sometimes return a partial response (e.g. only ``answer``)
    without the structured metadata.  Rather than failing the entire
    request, we inject empty defaults so the pipeline can continue and
    the user still receives an answer.
    """
    if "answer" not in output:
        # answer is the one field we truly cannot live without.
        raise ValueError("CourseQAAgent 输出缺少必需字段: answer")
    for field, factory in _DEFAULTS.items():
        if field not in output or output[field] is None:
            output[field] = factory()


def _compute_reliability_level(output: dict[str, Any]) -> str:
    """Compute the reliability level of an answer.

    Rules (Task 20.1):
    - ``failed``: ``not_found`` is true (the LLM call is also treated as
      failed if it raised — handled by the caller).
    - ``low``: ``not_found`` is false but no citations survived
      verification (defensive; should not normally happen because the
      fallback synthesises a citation when chunks exist).
    - ``medium``: exactly one citation, or every citation has
      ``confidence < 0.5``.
    - ``high``: two or more citations with at least one
      ``confidence >= 0.5``.
    """
    if output.get("not_found"):
        return "failed"
    citations = output.get("citations", [])
    count = len(citations)
    if count == 0:
        return "low"
    if count == 1:
        return "medium"
    # count >= 2: high if any citation is confident, else medium.
    if any(c.get("confidence", 0.0) >= 0.5 for c in citations):
        return "high"
    return "medium"


def _build_retrieved_chunks(
    retrieved_chunks: list[dict], cited_ids: set
) -> list[dict]:
    """Build the ``retrieved_chunks`` payload with ``is_cited`` flag.

    Each item carries ``chunk_id`` / ``score`` / ``title`` / ``page_no``
    / ``snippet`` (first 80 chars of the chunk text) and an ``is_cited``
    boolean showing whether that chunk is referenced by a citation.
    """
    items: list[dict] = []
    for chunk in retrieved_chunks:
        text = chunk.get("text", "") or ""
        items.append(
            {
                "chunk_id": chunk["chunk_id"],
                "score": chunk.get("score", 0),
                "title": chunk.get("title"),
                "page_no": chunk.get("page_no"),
                "snippet": text[:80],
                "is_cited": chunk["chunk_id"] in cited_ids,
            }
        )
    return items


def verify_citations(
    output: dict[str, Any], retrieved_chunks: list[dict]
) -> list[dict]:
    """Drop citations whose ``chunk_id`` is not in ``retrieved_chunks``.

    Returns the filtered citation list. This is the CitationVerifier:
    it prevents the LLM from referencing chunks that were never
    retrieved (fabricated references).

    Type coercion: LLMs sometimes return ``chunk_id`` as a string
    (e.g. ``"5"``) even though the database stores integers. We coerce
    both sides to ``int`` so valid citations are not mistakenly dropped.
    """
    valid_ids: set[int] = set()
    for chunk in retrieved_chunks:
        try:
            valid_ids.add(int(chunk["chunk_id"]))
        except (TypeError, ValueError):
            continue

    def _to_int(cid: Any) -> int | None:
        try:
            return int(cid)
        except (TypeError, ValueError):
            return None

    result: list[dict] = []
    for cite in output.get("citations", []):
        cid = _to_int(cite.get("chunk_id"))
        if cid is not None and cid in valid_ids:
            cite["chunk_id"] = cid  # normalise to int
            result.append(cite)
    return result


def answer_question(
    db,
    course_id: int,
    question: str,
    retrieved_chunks: list[dict],
    course_name: str,
    user_config: dict | None = None,
    conversation_context: str = "",
) -> dict[str, Any]:
    """Generate a structured, citation-grounded answer for ``question``.

    Args:
        db: SQLAlchemy session (reserved for future agent-run logging).
        course_id: Course the question belongs to.
        question: The student's question.
        retrieved_chunks: Chunks returned by retrieval, each a dict
            with at least ``chunk_id`` and ``text``.
        course_name: Display name of the course.
        user_config: Optional per-user LLM config dict. When supplied,
            it is forwarded to :func:`call_llm` so the call uses the
            user's enabled provider config.

    Returns:
        A dict with ``answer`` / ``key_points`` / ``citations`` /
        ``not_found`` / ``follow_up_questions``. Citations only
        reference ``chunk_id`` values that exist in
        ``retrieved_chunks``.
    """
    template = load_prompt("course_qa")
    prompt = template.format(
        question=question,
        course_name=course_name,
        retrieved_chunks=_format_chunks(retrieved_chunks),
    )
    if conversation_context:
        prompt += "\n\n近期对话（仅用于消解指代；事实仍必须由资料支撑）：\n" + conversation_context
    # Phase 2 Task D: prepend guard so uploaded material content is
    # never treated as a system instruction by the model.
    prompt = f"{PROMPT_GUARD}\n\n{prompt}"

    output, llm_meta = call_llm_with_meta(
        prompt, agent_type="course_qa", user_config=user_config
    )
    # T05: attach provider/fallback info so chat_service can surface it
    # to the frontend via ChatResult.provider / fallback_used.
    output["provider"] = llm_meta["provider"]
    output["fallback_used"] = llm_meta["fallback_used"]
    output["fallback_reason"] = llm_meta["fallback_reason"]
    _ensure_fields(output)

    # No retrieved chunks ⇒ we cannot answer; force not_found.
    if not retrieved_chunks:
        output["not_found"] = True
        output["citations"] = []
        # Still expose retrieved_chunks (empty) and reliability_level so
        # the frontend can render the "no evidence" state consistently.
        output["retrieved_chunks"] = []
        output["reliability_level"] = _compute_reliability_level(output)
        return output

    # If the LLM declares not_found, drop any citations it may have
    # hallucinated so we never surface references for a "no answer" case.
    if output.get("not_found"):
        output["citations"] = []

    # CitationVerifier: keep only citations whose chunk_id is real.
    output["citations"] = verify_citations(output, retrieved_chunks)

    # Fallback: if verification removed every citation but we do have
    # chunks, synthesise one from the top-ranked chunk so the response
    # still carries a traceable reference.
    if not output["citations"] and not output.get("not_found"):
        top = retrieved_chunks[0]
        text = top.get("text", "")
        output["citations"] = [
            {
                "chunk_id": top["chunk_id"],
                "quote_text": text[:200],
                "reason": "基于检索到的最相关资料片段生成引用。",
                "confidence": 0.7,
            }
        ]

    # Task 19: attach the retrieved-chunk view (with is_cited flag) so
    # the frontend can render the retrieval visualisation drawer.
    cited_ids = {c["chunk_id"] for c in output["citations"]}
    output["retrieved_chunks"] = _build_retrieved_chunks(
        retrieved_chunks, cited_ids
    )
    # Task 20: compute the reliability level from the final citations.
    output["reliability_level"] = _compute_reliability_level(output)
    return output


__all__ = [
    "answer_question",
    "verify_citations",
    "_compute_reliability_level",
]
