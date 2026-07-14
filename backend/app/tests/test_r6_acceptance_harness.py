from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.services.real_llm_acceptance_service import RealLLMAcceptanceError


PROJECT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_DIR / "scripts" / "verify_real_llm_acceptance.py"
PROMPT_PATH = PROJECT_DIR / "backend" / "app" / "agents" / "prompts" / "outline_repair_v1.md"
PLANNER_PROMPT_PATH = PROJECT_DIR / "backend" / "app" / "agents" / "prompts" / "planner_v1.md"


def _load_harness():
    spec = importlib.util.spec_from_file_location("verify_real_llm_acceptance_r6", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_record(**updates):
    record = {
        "id": 2,
        "run_type": "outline",
        "status": "success",
        "provider": "real",
        "actual_provider": "user",
        "model_name": "model-a",
        "actual_model": "model-a",
        "fallback_used": False,
        "duration_ms": 10,
        "output_summary": {"meta_observed": True},
    }
    record.update(updates)
    return record


def test_harness_does_not_infer_meta_observed(monkeypatch) -> None:
    harness = _load_harness()
    run = _run_record(output_summary={})
    monkeypatch.setattr(harness, "_runs", lambda _client: [run])

    with pytest.raises(RealLLMAcceptanceError, match="REAL_LLM_META_MISSING"):
        harness._assert_new_real_run(None, {1}, "outline")


def test_harness_does_not_coerce_missing_fallback_state(monkeypatch) -> None:
    harness = _load_harness()
    run = _run_record(fallback_used=None)
    monkeypatch.setattr(harness, "_runs", lambda _client: [run])

    with pytest.raises(RealLLMAcceptanceError, match="REAL_LLM_FALLBACK_STATE_MISSING"):
        harness._assert_new_real_run(None, {1}, "outline")


def test_harness_accepts_only_explicit_success_meta(monkeypatch) -> None:
    harness = _load_harness()
    run = _run_record()
    monkeypatch.setattr(harness, "_runs", lambda _client: [run])

    result = harness._assert_new_real_run(None, {1}, "outline")

    assert result["meta_observed"] is True
    assert result["fallback_used"] is False


def test_outline_repair_prompt_is_course_generic() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "至少 2 条" in prompt
    assert "实际存在且能支持该知识点的 chunk_id" in prompt
    assert "CRC" not in prompt
    assert "停止等待" not in prompt
    assert "滑动窗口" not in prompt


def test_planner_prompt_requires_a_material_learning_task_per_course() -> None:
    prompt = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")

    assert "每门关联课程至少安排一项 `learn` 任务" in prompt
    assert "已上传的资料" in prompt
