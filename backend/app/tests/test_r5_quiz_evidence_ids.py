from app.agents.quiz import _canonical_chunk_id


def test_quiz_accepts_only_exact_prompt_chunk_id_forms() -> None:
    assert _canonical_chunk_id(12) == 12
    assert _canonical_chunk_id("chunk_id=12") == 12
    assert _canonical_chunk_id("chunk_id_12") == 12
    assert _canonical_chunk_id("chunk 12") is None
    assert _canonical_chunk_id("missing") is None
