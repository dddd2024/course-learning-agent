"""AI-based chunk quality evaluation service.

Provides batch quality evaluation for document chunks using LLM.
Falls back to heuristic scoring when LLM is unavailable.
"""
import logging
from typing import Any

from app.agents.llm import call_llm, _heuristic_quality_score

logger = logging.getLogger(__name__)

BATCH_SIZE = 5
QUALITY_THRESHOLD = 0.3  # Chunks below this are filtered in frontend


def evaluate_chunks_quality(
    chunks: list[dict[str, Any]],
    user_config: dict | None = None,
) -> list[dict[str, float | str]]:
    """Evaluate quality of document chunks in batches using LLM.

    Args:
        chunks: List of dicts with "text" and "index" keys.
        user_config: Optional per-user LLM config.

    Returns:
        List of {"quality": float, "reason": str} for each input chunk,
        in the same order as input.
    """
    if not chunks:
        return []

    results: list[dict[str, float | str]] = []

    # Process in batches
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        batch_results = _evaluate_batch(batch, user_config)
        results.extend(batch_results)

    return results


def _evaluate_batch(
    batch: list[dict[str, Any]],
    user_config: dict | None = None,
) -> list[dict[str, float | str]]:
    """Evaluate a single batch of chunks via LLM."""
    from app.agents.prompt_loader import load_prompt

    # Build the chunks text for the prompt
    chunks_text = ""
    for j, chunk in enumerate(batch):
        text = chunk.get("text", "").strip()
        chunks_text += f"\n[片段{j}]\n{text}\n"

    try:
        template = load_prompt("chunk_quality")
        prompt = template.format(chunks=chunks_text)
        output = call_llm(prompt, agent_type="chunk_quality", user_config=user_config)
        evaluations = output.get("evaluations", [])

        # Map evaluations back to batch order
        result_map = {ev["index"]: ev for ev in evaluations}
        results = []
        for j in range(len(batch)):
            ev = result_map.get(j)
            if ev:
                results.append({
                    "quality": float(ev.get("quality", 0.5)),
                    "reason": ev.get("reason", ""),
                })
            else:
                # Fallback to heuristic if LLM missed this chunk
                score, reason = _heuristic_quality_score(batch[j].get("text", ""))
                results.append({"quality": score, "reason": reason})
        return results

    except Exception as e:
        logger.warning("LLM chunk quality evaluation failed, using heuristics: %s", e)
        # Fallback to heuristic scoring
        results = []
        for chunk in batch:
            score, reason = _heuristic_quality_score(chunk.get("text", ""))
            results.append({"quality": score, "reason": reason})
        return results
