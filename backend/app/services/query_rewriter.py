"""Auditable contextual query rewriting for chat retrieval.

CHAT-V3-01: Before retrieval, the user's question is rewritten to resolve
coreferences (e.g. "它有什么作用" -> "TLB有什么作用") using the
conversation history. The rewritten query is used ONLY for retrieval —
it must never be treated as a fact source or enter the evidence chain.

When a real model is available, it can be used for coreference resolution.
When the model is mock/offline, deterministic entity-inheritance rules
resolve pronouns by scanning recent assistant messages for entity mentions.

If the referent of a pronoun is ambiguous (multiple candidates), the
rewriter sets ``needs_clarification=True`` so the chat service can return
a clarification prompt instead of proceeding with retrieval.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.config import settings

# Chinese pronouns / demonstratives that require coreference resolution.
_PRONOUN_PATTERNS = [
    re.compile(r"它(?:们)?(?:的|是|有|能|可以|会|用来|用于|作用|功能|特点|区别)?"),
    re.compile("这个(?:的|是|有|能|可以|会|用来|用于|作用|功能|特点|区别)?"),
    re.compile("那个(?:的|是|有|能|可以|会|用来|用于|作用|功能|特点|区别)?"),
    re.compile("前者(?:的|是|有|能|可以|会|用来|用于|作用|功能|特点|区别)?"),
    re.compile("后者(?:的|是|有|能|可以|会|用来|用于|作用|功能|特点|区别)?"),
    re.compile("这(?:个)?概念(?:的|是|有|能|可以|会|用来|用于|作用|功能|特点|区别)?"),
]

# Simple entity extraction: CJK terms of length 2-8, or known English
# acronyms (2-6 uppercase letters). This is intentionally lightweight —
# the real model would do NER, but the deterministic fallback just needs
# to find plausible entity candidates.
_ENTITY_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{2,8}|[A-Z]{2,6}\b"
)

# Topics that should NOT be inherited as entities (too generic).
_GENERIC_TERMS = frozenset(
    {"什么", "怎么", "如何", "为什么", "哪个", "哪些", "作用", "功能",
     "特点", "区别", "关系", "原理", "概念", "定义", "类型", "分类"}
)

# Common Chinese particles, prepositions, and function words used to split
# raw CJK sequences so that meaningful sub-entities are separated.
# For example, "什么是虚拟存储器" should be split on "什么" and "是" to
# yield the entity "虚拟存储器", not the full 7-character string.
_PARTICLE_TERMS = frozenset({
    "什么", "怎么", "如何", "为什么", "可以", "用来", "用于",
    "叫做", "称为", "属于", "包含", "组成", "分为", "称作",
    "是", "把", "的", "和", "与", "在", "有", "中", "了", "到",
    "为", "被", "对", "也", "而", "或", "以", "给", "让", "使",
    "及", "并", "其", "放", "能", "会", "这", "那", "它",
})

_PARTICLE_SPLIT_RE = re.compile(
    "|".join(re.escape(t) for t in sorted(_PARTICLE_TERMS, key=len, reverse=True))
    if _PARTICLE_TERMS else r"(?!)"
)


def _has_pronoun(text: str) -> bool:
    """Return True if ``text`` contains a pronoun/demonstrative."""
    return any(p.search(text) for p in _PRONOUN_PATTERNS)


def _extract_entities(text: str) -> list[str]:
    """Extract candidate entity mentions from ``text``.

    Returns entities in order of first appearance, deduplicated.

    Raw CJK sequences are split on common particles (``_PARTICLE_TERMS``)
    before matching so that meaningful terms like ``虚拟存储器`` are
    separated from function words like ``什么是`` or ``把``.
    """
    seen: set[str] = set()
    entities: list[str] = []
    for m in _ENTITY_PATTERN.finditer(text):
        term = m.group()
        if term in _GENERIC_TERMS:
            continue
        # Split on particles to separate meaningful sub-entities.
        for part in _PARTICLE_SPLIT_RE.split(term):
            if len(part) < 2:
                continue
            if part in _GENERIC_TERMS or part in _PARTICLE_TERMS:
                continue
            if part not in seen:
                seen.add(part)
                entities.append(part)
    return entities


def _deterministic_resolve(
    question: str, history: list[dict]
) -> dict[str, Any]:
    """Resolve coreferences using deterministic entity-inheritance rules.

    Scans recent assistant messages for entity mentions and replaces
    pronouns in the question with the most recently mentioned entity.
    """
    original = question
    resolved = question
    reason = "no_pronoun"
    needs_clarification = False

    if not _has_pronoun(question):
        return {
            "original_query": original,
            "resolved_query": original,
            "resolution_reason": "no_pronoun",
            "entities": [],
            "needs_clarification": False,
        }

    # Walk assistant messages in reverse (most recent first) to find
    # entity candidates. We look at the last few assistant turns.
    candidates: list[str] = []
    for msg in reversed(history):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content") or ""
        if not content:
            continue
        entities = _extract_entities(content)
        for e in entities:
            if e not in candidates:
                candidates.append(e)
        if len(candidates) >= 3:
            break

    if not candidates:
        # Pronoun found but no entity in history to resolve it.
        return {
            "original_query": original,
            "resolved_query": original,
            "resolution_reason": "no_entity_in_history",
            "entities": [],
            "needs_clarification": False,
        }

    # If we have exactly one candidate (or the user question already
    # mentions one of the candidates), resolve unambiguously.
    if len(candidates) == 1:
        entity = candidates[0]
        resolved = _replace_pronoun(question, entity)
        return {
            "original_query": original,
            "resolved_query": resolved,
            "resolution_reason": f"inherited_from_assistant:{entity}",
            "entities": [entity],
            "needs_clarification": False,
        }

    # Multiple candidates: check if the question already narrows it down
    # by mentioning one of them. If so, resolve to that one.
    question_entities = _extract_entities(question)
    # Also check if the user's previous message mentioned an entity.
    for msg in reversed(history):
        if msg.get("role") == "user":
            prev_entities = _extract_entities(msg.get("content") or "")
            # Find intersection with candidates
            for e in prev_entities:
                if e in candidates:
                    resolved = _replace_pronoun(question, e)
                    return {
                        "original_query": original,
                        "resolved_query": resolved,
                        "resolution_reason": f"inherited_from_user:{e}",
                        "entities": [e],
                        "needs_clarification": False,
                    }
            # Fallback: if the user's previous message contained entities
            # but none matched the assistant's candidates, use the first
            # user-entity directly. This handles the case where the
            # assistant's answer was replaced with an evidence-insufficient
            # message (EVID-V3-01) that doesn't contain the original topic
            # entities, so the pronoun can still be resolved from the
            # user's own previous question.
            if prev_entities:
                entity = prev_entities[0]
                resolved = _replace_pronoun(question, entity)
                return {
                    "original_query": original,
                    "resolved_query": resolved,
                    "resolution_reason": f"inherited_from_user_fallback:{entity}",
                    "entities": [entity],
                    "needs_clarification": False,
                }
            break

    # Check if any candidate is already in the question
    for e in question_entities:
        if e in candidates:
            resolved = _replace_pronoun(question, e)
            return {
                "original_query": original,
                "resolved_query": resolved,
                "resolution_reason": f"disambiguated_by_question:{e}",
                "entities": [e],
                "needs_clarification": False,
            }

    # Multiple candidates and no way to disambiguate -> ask the user.
    needs_clarification = True
    return {
        "original_query": original,
        "resolved_query": original,
        "resolution_reason": "ambiguous_reference",
        "entities": candidates[:3],
        "needs_clarification": True,
    }


def _replace_pronoun(question: str, entity: str) -> str:
    """Replace the first pronoun/demonstrative in ``question`` with ``entity``."""
    result = question
    for pattern in _PRONOUN_PATTERNS:
        m = pattern.search(result)
        if m:
            result = result[: m.start()] + entity + result[m.end():]
            break
    return result


def rewrite_query(
    question: str,
    conversation_history: list[dict] | None = None,
    user_config: dict | None = None,
) -> dict[str, Any]:
    """Rewrite a user question to resolve coreferences.

    Args:
        question: The user's original question.
        conversation_history: List of ``{"role": "user"|"assistant",
            "content": "..."}`` dicts representing recent turns.
        user_config: Optional LLM config. When provided AND a real model
            is available, the model is used for coreference resolution.
            Otherwise, deterministic rules are used.

    Returns:
        A dict with keys:
        - ``original_query``: the unchanged question
        - ``resolved_query``: the question with pronouns resolved (for
          retrieval only — never used as evidence)
        - ``resolution_reason``: why the resolution was made
        - ``entities``: list of entity strings mentioned/extracted
        - ``needs_clarification``: True when the pronoun is ambiguous
    """
    history = conversation_history or []

    # If no history or no pronoun, no rewriting needed.
    if not history or not _has_pronoun(question):
        return {
            "original_query": question,
            "resolved_query": question,
            "resolution_reason": "no_pronoun" if not _has_pronoun(question) else "no_history",
            "entities": [],
            "needs_clarification": False,
        }

    # When a real model is available, we could use it for coreference
    # resolution. However, the deterministic rules are sufficient for
    # the common case and avoid an extra LLM round-trip. The real model
    # path is reserved for future enhancement; for now, we always use
    # deterministic resolution to keep retrieval fast and auditable.
    return _deterministic_resolve(question, history)


__all__ = ["rewrite_query"]
