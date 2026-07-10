"""Tests for agent audit metadata accuracy."""
from app.agents.audit import AgentAudit


def test_quiz_audit_records_real_provider():
    """Quiz audit run should record the actual provider, not hardcoded 'mock'."""
    import inspect
    from app.agents import quiz
    source = inspect.getsource(quiz.generate_quiz)

    # The create_run call should NOT hardcode model_name="mock"
    assert 'model_name="mock"' not in source, (
        "quiz.py still hardcodes model_name='mock' in create_run"
    )


def test_concept_compare_audit_records_real_provider():
    """Concept compare audit run should record actual provider."""
    import inspect
    from app.agents import concept_compare
    source = inspect.getsource(concept_compare.generate_compare)

    assert 'model_name="mock"' not in source, (
        "concept_compare.py still hardcodes model_name='mock' in create_run"
    )
    assert 'provider="mock"' not in source, (
        "concept_compare.py still hardcodes provider='mock' in create_run"
    )


def test_llm_meta_includes_model_name():
    """call_llm_with_meta should include model_name in the returned meta."""
    from app.agents.llm import call_llm_with_meta
    result, meta = call_llm_with_meta("test", "course_qa")
    assert "model_name" in meta, (
        f"meta should include 'model_name', got keys: {list(meta.keys())}"
    )


def test_audit_update_run_meta_exists():
    """AgentAudit should have an update_run_meta method."""
    assert hasattr(AgentAudit, 'update_run_meta'), (
        "AgentAudit should have update_run_meta method"
    )
