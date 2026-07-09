"""Tests for the LLM adapter layer and prompt template loader.

These tests pin down the contract of ``call_llm`` (mock provider) and
``load_prompt``. The mock provider must return structured JSON matching
the schema required by each agent type so the platform can be demoed
without an API key.
"""
import json

from app.agents.llm import call_llm
from app.agents.prompt_loader import load_prompt


def test_call_llm_mock_returns_valid_json(monkeypatch) -> None:
    """When LLM_PROVIDER==mock, call_llm returns a JSON dict."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")

    schema = {
        "type": "object",
        "required": ["answer", "key_points", "citations", "not_found",
                     "follow_up_questions"],
    }
    result = call_llm(
        prompt="请回答：什么是梯度下降？",
        agent_type="course_qa",
        schema=schema,
    )

    assert isinstance(result, dict)
    for field in schema["required"]:
        assert field in result


def test_call_llm_mock_course_qa(monkeypatch) -> None:
    """course_qa mock returns answer/key_points/citations/not_found/follow_up_questions."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")

    result = call_llm(
        prompt="系统角色:课程学习助手\n用户问题:什么是梯度下降?",
        agent_type="course_qa",
    )

    assert isinstance(result["answer"], str)
    assert isinstance(result["key_points"], list)
    assert isinstance(result["citations"], list)
    assert isinstance(result["not_found"], bool)
    assert isinstance(result["follow_up_questions"], list)
    # citations 结构校验
    if result["citations"]:
        cite = result["citations"][0]
        assert "chunk_id" in cite
        assert "quote_text" in cite
        assert "reason" in cite
        assert "confidence" in cite
        assert isinstance(cite["confidence"], (int, float))


def test_call_llm_mock_outline(monkeypatch) -> None:
    """outline mock returns a knowledge_points list."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")

    result = call_llm(
        prompt=(
            "从以下 chunks 提取知识点:\n\n"
            "[片段1] chunk_id=1\n"
            "TCP协议是传输控制协议，提供可靠的、面向连接的字节流服务。\n\n"
            "[片段2] chunk_id=2\n"
            "UDP是用户数据报协议，提供无连接的、不可靠的数据传输服务。"
        ),
        agent_type="outline",
    )

    assert "knowledge_points" in result
    assert isinstance(result["knowledge_points"], list)
    assert len(result["knowledge_points"]) > 0
    point = result["knowledge_points"][0]
    for field in ("title", "summary", "importance", "source_chunk_ids",
                  "exam_style", "review_action"):
        assert field in point
    assert isinstance(point["source_chunk_ids"], list)


def test_call_llm_mock_planner(monkeypatch) -> None:
    """planner mock returns goal_title and tasks list."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")

    result = call_llm(
        prompt="目标：两周内复习完《机器学习》前五章",
        agent_type="planner",
    )

    assert "goal_title" in result
    assert isinstance(result["goal_title"], str)
    assert "tasks" in result
    assert isinstance(result["tasks"], list)
    assert len(result["tasks"]) > 0
    task = result["tasks"][0]
    for field in ("course_name", "title", "task_type", "estimate_minutes",
                  "priority", "acceptance"):
        assert field in task
    assert isinstance(task["estimate_minutes"], int)
    assert isinstance(task["priority"], int)


def test_load_prompt() -> None:
    """load_prompt('course_qa', 'v1') returns the prompt file content string."""
    content = load_prompt("course_qa", "v1")

    assert isinstance(content, str)
    assert len(content) > 0
    # 占位符应存在
    assert "{question}" in content or "{retrieved_chunks}" in content


def test_load_prompt_all_agent_types() -> None:
    """All declared prompt templates should be loadable."""
    for agent_type in (
        "course_qa", "outline", "planner", "task_decompose",
        "multi_course_schedule", "quiz_generate", "citation_verify",
    ):
        content = load_prompt(agent_type, "v1")
        assert isinstance(content, str)
        assert len(content) > 0


def test_call_llm_invalid_json_handling(monkeypatch) -> None:
    """Mock provider always returns valid JSON; it should never raise."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")

    # 反复调用多种 agent_type，不应抛异常
    for agent_type in (
        "course_qa", "outline", "planner", "task_decompose",
        "multi_course_schedule", "quiz_generate", "citation_verify",
    ):
        result = call_llm(prompt="anything", agent_type=agent_type)
        # 必须是可序列化的 dict
        assert isinstance(result, dict)
        # 验证确实可被 json 序列化（确保返回的是普通 dict 而非特殊对象）
        json.dumps(result)
