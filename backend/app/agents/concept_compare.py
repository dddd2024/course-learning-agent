"""Concept compare agent: generates structured cross-course compare reports.

Follows the existing agent pattern: load_prompt -> call_llm_with_meta ->
validate -> return dict. Uses a structured mock fallback when the LLM
is unavailable or returns a non-compare-shaped payload.

Note: ``call_llm_with_meta`` in this codebase returns ``(result_dict, meta)``
where ``result_dict`` is already a parsed JSON dict (or a generic envelope
for unknown agent types). We detect a valid compare response by checking
for the ``concept_a`` / ``similarities`` keys; otherwise we fall back.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.audit import AgentAudit
from app.agents.llm import call_llm_with_meta
from app.agents.prompt_loader import load_prompt
from app.core.config import settings

logger = logging.getLogger(__name__)

_PROMPT_VERSION = "v1"


def generate_compare(
    db,
    user_id: int,
    concept_a: dict,
    concept_b: dict,
    evidence_chunks: list[dict] | None = None,
    user_config: dict | None = None,
    user_focus: str = "concept",
) -> dict:
    """Generate a structured compare report for two concepts.

    Returns a dict with: report_json, citation_chunk_ids, provider,
    model_name, fallback_used, fallback_reason, audit_run_id.
    """
    import json

    # Determine provider/model_name before LLM call (best guess).
    if user_config:
        _provider = "user"
        _model = user_config.get("model", "")
    else:
        _provider = "real" if settings.LLM_PROVIDER == "real" else "mock"
        _model = settings.LLM_MODEL

    run = AgentAudit.create_run(
        db,
        user_id,
        run_type="concept_compare",
        input_summary={
            "a": concept_a.get("title"),
            "b": concept_b.get("title"),
        },
        prompt_version=_PROMPT_VERSION,
        model_name=_model,
        provider=_provider,
    )

    try:
        prompt_template = load_prompt("concept_compare", version=_PROMPT_VERSION)
        evidence_text = json.dumps(evidence_chunks or [], ensure_ascii=False)
        prompt = prompt_template.format(
            concept_a_title=concept_a.get("title", ""),
            concept_a_summary=concept_a.get("summary", ""),
            concept_b_title=concept_b.get("title", ""),
            concept_b_summary=concept_b.get("summary", ""),
            evidence=evidence_text,
            user_focus=user_focus,
        )

        result, meta = call_llm_with_meta(
            prompt, agent_type="concept_compare", user_config=user_config
        )

        # Update audit run with actual provider/model_name from meta
        AgentAudit.update_run_meta(
            db, run.id,
            model_name=meta.get("model_name"),
            provider=meta.get("provider"),
        )

        if _is_valid_compare_report(result):
            AgentAudit.add_step(
                db, run.id, "generate", 0,
                output_data={"keys": list(result.keys())},
            )
            AgentAudit.finish_run(
                db, run.id, status="success",
                output_summary={"keys": list(result.keys())},
            )
            return {
                "report_json": result,
                "citation_chunk_ids": _extract_citation_ids(result),
                "provider": meta.get("provider", "mock"),
                "model_name": meta.get("model_name", "mock"),
                "fallback_used": bool(meta.get("fallback_used", False)),
                "fallback_reason": meta.get("fallback_reason") or "",
                "audit_run_id": run.id,
            }

        # LLM returned a generic/unknown envelope -> use structured mock.
        return _mock_fallback(
            db, run, concept_a, concept_b,
            reason="LLM 返回非对比报告结构，使用 mock fallback",
        )
    except Exception as exc:  # noqa: BLE001 - demo must stay up
        logger.warning("compare agent failed, using mock fallback: %s", exc)
        return _mock_fallback(
            db, run, concept_a, concept_b,
            reason=f"LLM 调用失败: {exc}",
        )


def _is_valid_compare_report(result: Any) -> bool:
    """Return True if ``result`` looks like a compare report dict.

    Also fills in any missing required sections with empty arrays so the
    frontend never crashes on a missing key (Task 9 Issue D).
    """
    if not isinstance(result, dict):
        return False
    if "concept_a" not in result and "similarities" not in result:
        return False
    # Ensure all required sections exist (can be empty arrays but must exist)
    # so the frontend's optional-chaining access (e.g. report_json.similarities)
    # never hits a missing key.
    required_sections = (
        "similarities", "differences",
        "transfer_learning", "confusions", "exam_questions",
    )
    for section in required_sections:
        if section not in result:
            result[section] = []  # fill missing sections with empty arrays
    return True


def _extract_citation_ids(report: dict) -> list[int]:
    ids: list[int] = []
    for c in report.get("citations", []) or []:
        if isinstance(c, dict) and "chunk_id" in c:
            try:
                ids.append(int(c["chunk_id"]))
            except (TypeError, ValueError):
                continue
    return ids


def _mock_fallback(
    db, run, concept_a: dict, concept_b: dict, reason: str
) -> dict:
    """Generate a structured mock compare report when LLM is unavailable."""
    report = {
        "concept_a": {
            "title": concept_a.get("title", ""),
            "explanation": concept_a.get("summary", ""),
        },
        "concept_b": {
            "title": concept_b.get("title", ""),
            "explanation": concept_b.get("summary", ""),
        },
        "similarities": ["两者都是重要概念，需要理解其核心定义"],
        "differences": [
            {
                "dimension": "所属领域",
                "a": concept_a.get("summary", ""),
                "b": concept_b.get("summary", ""),
            }
        ],
        "transfer_learning": ["对比两者的核心思想，寻找可迁移的方法论"],
        "confusions": ["注意两者的适用场景差异"],
        "exam_questions": ["简述两者的联系与区别"],
        "citations": [],
        "insufficient_evidence": True,
    }
    AgentAudit.add_step(
        db, run.id, "generate", 0,
        output_data={"fallback": True},
    )
    AgentAudit.finish_run(
        db, run.id, status="success",
        output_summary={"fallback": True},
    )
    return {
        "report_json": report,
        "citation_chunk_ids": [],
        "provider": "mock",
        "model_name": "mock",
        "fallback_used": True,
        "fallback_reason": reason,
        "audit_run_id": run.id,
    }


__all__ = ["generate_compare"]
