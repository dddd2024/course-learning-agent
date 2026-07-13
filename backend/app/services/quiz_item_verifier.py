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

    if question_type in ("single_choice", "choice"):
        return _verify_choice_item(item, combined_quote)
    elif question_type == "multiple_choice":
        return _verify_multiple_choice_item(item, combined_quote)
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

    option_texts = []
    for opt in options:
        option_texts.append(str(opt.get("text", "")).strip() if isinstance(opt, dict) else str(opt)[2:].strip())
    if len(option_texts) < 3 or len(set(option_texts)) != len(option_texts):
        return False, "单选题选项数量不足或存在重复"
    exact_matches = [text for text in option_texts if text and text in combined_quote]
    if len(exact_matches) != 1:
        return False, "单选题必须恰有一个选项与来源引用精确匹配"
    if correct_text != exact_matches[0]:
        return False, "正确答案不是唯一的来源精确匹配选项"
    return True, "verified"


def _verify_multiple_choice_item(
    item: dict[str, Any],
    combined_quote: str,
) -> tuple[bool, str]:
    """Verify that every and only selected option is directly evidenced."""
    options = item.get("options", [])
    answer = item.get("answer")
    if not isinstance(options, list) or len(options) < 4:
        return False, "多选题至少需要四个选项"
    if not isinstance(answer, list) or len(answer) < 2:
        return False, "多选题答案必须是至少两个选项字母组成的数组"

    by_label: dict[str, str] = {}
    for index, option in enumerate(options):
        if isinstance(option, dict):
            label = str(option.get("label", option.get("value", ""))).strip().upper()
            text = str(option.get("text", "")).strip()
        else:
            raw = str(option).strip()
            label = raw[:1].upper() if len(raw) > 1 and raw[1] in ".、)" else chr(65 + index)
            text = raw[2:].strip() if len(raw) > 1 and raw[1] in ".、)" else raw
        if not label or not text or label in by_label:
            return False, "多选题选项标签或文本无效"
        by_label[label] = text

    selected = [str(value).strip().upper() for value in answer]
    if len(set(selected)) != len(selected) or any(value not in by_label for value in selected):
        return False, "多选题答案包含无效或重复选项"
    matching = {label for label, text in by_label.items() if text in combined_quote}
    if matching != set(selected):
        return False, "多选题来源精确匹配选项必须与答案数组完全一致"
    return True, "verified"


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

    answer = str(item.get("answer", "")).strip().lower()
    corrected = str(item.get("corrected_statement", "")).strip()
    if answer in {"true", "正确", "是"}:
        if statement not in combined_quote:
            return False, "true 判断题陈述必须是来源引用的精确子串"
        if any(token in statement for token in ("不是", "不能", "从不", "必然", "全部")):
            return False, "true 判断题含未被证据支持的极性词"
        return True, "verified"
    if answer in {"false", "错误", "否"}:
        if not corrected or corrected not in combined_quote or statement == combined_quote:
            return False, "false 判断题必须提供来源支持的 corrected_statement"
        return True, "verified"
    return False, "判断题答案必须为 true 或 false"

    # Kept unreachable for compatibility with older source maps.
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
