"""QUIZ-V3-02: Verify quiz items against their source evidence.

Each quiz item must be grounded in verifiable course material. This module
provides ``verify_quiz_item`` which checks that:

1. ``source_evidence`` contains at least one valid ``{chunk_id, quote_text}``
   entry whose ``quote_text`` is a substring of the actual chunk text.
2. For **choice** questions: the correct answer text can be found in or
   derived from one of the source quotes.
3. For **true_false** questions: the statement in the stem can be judged
   from the source quote (i.e. the stem overlaps with the quote text).
4. For **short_answer** questions: each rubric criterion has at least one
   source quote that supports it.

Returns ``(is_valid, reason)`` where ``reason`` is a human-readable
explanation when invalid.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def verify_quiz_item(
    item: dict[str, Any],
    evidence_chunks: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Verify a quiz item against its source evidence.

    Parameters
    ----------
    item
        The quiz item dict produced by ``generate_quiz``. Expected keys:
        ``question_type``, ``question_text``, ``options``, ``answer``,
        ``rubric``, and ``source_evidence``.
    evidence_chunks
        List of chunk dicts with ``id`` and ``text`` keys representing the
        active material chunks for the course.

    Returns
    -------
    tuple[bool, str]
        ``(True, "verified")`` when the item passes all checks, otherwise
        ``(False, reason)`` with a human-readable explanation.
    """
    source_evidence = item.get("source_evidence", [])
    if not isinstance(source_evidence, list) or not source_evidence:
        return False, "缺少 source_evidence，无法验证题目来源"

    # Build a lookup from chunk_id to chunk text.
    chunk_lookup: dict[int, str] = {}
    for chunk in evidence_chunks:
        cid = chunk.get("id") or chunk.get("chunk_id")
        if cid is not None:
            chunk_lookup[int(cid)] = chunk.get("text", "")

    # Verify each source_evidence entry.
    valid_quotes: list[str] = []
    for ev in source_evidence:
        if not isinstance(ev, dict):
            continue
        chunk_id = ev.get("chunk_id")
        quote_text = ev.get("quote_text", "")
        if chunk_id is None or not quote_text:
            continue
        chunk_id_int = int(chunk_id) if not isinstance(chunk_id, int) else chunk_id
        chunk_text = chunk_lookup.get(chunk_id_int, "")
        if not chunk_text:
            return False, f"chunk_id {chunk_id} 不存在于课程资料中"
        if quote_text not in chunk_text:
            return False, (
                f"quote_text 不是 chunk_id {chunk_id} 原文的子串"
            )
        valid_quotes.append(quote_text)

    if not valid_quotes:
        return False, "source_evidence 中没有有效的引用条目"

    # Type-specific verification.
    question_type = item.get("question_type", "")
    combined_quote = " ".join(valid_quotes)

    if question_type in ("single_choice", "multiple_choice", "choice"):
        return _verify_choice_item(item, combined_quote)
    elif question_type == "true_false":
        return _verify_true_false_item(item, combined_quote)
    elif question_type == "short_answer":
        return _verify_short_answer_item(item, valid_quotes)
    else:
        # Unknown type — accept if it has valid source evidence.
        return True, "verified"


def _verify_choice_item(
    item: dict[str, Any],
    combined_quote: str,
) -> tuple[bool, str]:
    """Verify a choice question: correct answer text should appear in
    or be derivable from the source quote."""
    options = item.get("options", [])
    answer = str(item.get("answer", "")).strip()

    if not options or not answer:
        return False, "选择题缺少选项或答案"

    # Find the correct option text by matching the answer label (A/B/C/D).
    correct_text = ""
    for opt in options:
        if isinstance(opt, dict):
            label = str(opt.get("label", opt.get("value", ""))).strip()
            if label.upper() == answer.upper():
                correct_text = str(opt.get("text", ""))
                break
        elif isinstance(opt, str):
            # Options may be prefixed like "A. text"
            if opt[:1].strip().upper() == answer.upper():
                correct_text = opt[1:].lstrip(".、) ").strip()
                break

    if not correct_text:
        return False, f"无法找到答案 {answer} 对应的选项文本"

    # The correct option text should appear in the source quote, or at
    # least share significant overlap with it.
    if correct_text in combined_quote:
        return True, "verified"

    # Check for partial overlap (at least 4 consecutive characters).
    min_overlap = 4
    for i in range(len(correct_text) - min_overlap + 1):
        substr = correct_text[i : i + min_overlap]
        if substr in combined_quote:
            return True, "verified"

    return False, (
        f"正确选项「{correct_text[:40]}」未在来源引用中出现"
    )


def _verify_true_false_item(
    item: dict[str, Any],
    combined_quote: str,
) -> tuple[bool, str]:
    """Verify a true/false question: the statement should be judgeable
    from the source quote (i.e. the stem overlaps with the quote)."""
    stem = item.get("question_text", "")
    if not stem:
        return False, "判断题缺少题干"

    # Extract the statement part after any prefix like "根据课程资料，"
    # or "以下说法是否正确："
    statement = stem
    for sep in ["：", ":", "，", ","]:
        parts = statement.split(sep, 1)
        if len(parts) > 1 and len(parts[1].strip()) > 5:
            statement = parts[1].strip()
            break

    if not statement:
        statement = stem

    # Check that the statement shares at least some overlap with the quote.
    min_overlap = 4
    for i in range(len(statement) - min_overlap + 1):
        substr = statement[i : i + min_overlap]
        if substr in combined_quote:
            return True, "verified"

    return False, (
        f"判断题陈述未在来源引用中出现，无法从原文判断"
    )


def _verify_short_answer_item(
    item: dict[str, Any],
    valid_quotes: list[str],
) -> tuple[bool, str]:
    """Verify a short-answer question: each rubric criterion should have
    at least one source quote that supports it."""
    rubric = item.get("rubric", [])
    if not rubric:
        # If no rubric, check that the answer text appears in the quotes.
        answer = str(item.get("answer", ""))
        combined = " ".join(valid_quotes)
        if answer and answer in combined:
            return True, "verified"
        # Also accept if there's partial overlap
        if answer:
            min_overlap = 3
            for i in range(len(answer) - min_overlap + 1):
                if answer[i : i + min_overlap] in combined:
                    return True, "verified"
        return False, "简答题缺少评分标准且答案未在来源引用中出现"

    combined = " ".join(valid_quotes)
    for i, criterion in enumerate(rubric):
        if not isinstance(criterion, dict):
            continue
        keywords = criterion.get("keywords", [])
        if not keywords:
            # If no keywords, accept if criterion text overlaps with quote.
            crit_text = criterion.get("criterion", "")
            if crit_text:
                min_overlap = 3
                found = False
                for j in range(len(crit_text) - min_overlap + 1):
                    if crit_text[j : j + min_overlap] in combined:
                        found = True
                        break
                if not found:
                    return False, f"评分标准 {i+1} 未在来源引用中找到支持"
            continue
        # Check that at least one keyword appears in the source quotes.
        found = False
        for kw in keywords:
            if kw in combined:
                found = True
                break
        if not found:
            return False, (
                f"评分标准 {i+1} 的关键词 {keywords} 未在来源引用中出现"
            )

    return True, "verified"
