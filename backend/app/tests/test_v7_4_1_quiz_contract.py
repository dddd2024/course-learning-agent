"""V7.4.1-03: Quiz generation contract propagation (TDD).

Strict TDD: these tests are written FIRST and fail until the quiz
generation prompt propagates the requested ``question_types``,
``difficulty_distribution``, and ``question_count`` into the LLM prompt.

RED phase state:
- ``build_quiz_prompt`` does not exist yet.
- The prompt template ``quiz_generate_v1.md`` has no
  ``{difficulty_distribution}`` placeholder.
- The endpoint / ``QuizCreationService`` does not forward the contract
  parameters to ``generate_quiz`` (and thus to the prompt builder).
"""
from app.agents.prompt_loader import load_prompt
from app.tests.conftest import auth_headers, setup_course_with_material


# ---------------------------------------------------------------------------
# 1. Prompt template includes the contract placeholders
# ---------------------------------------------------------------------------


def test_prompt_template_includes_contract_placeholders() -> None:
    """The prompt template must expose all three contract placeholders."""
    template = load_prompt("quiz_generate")
    assert "{question_types}" in template
    assert "{difficulty_distribution}" in template
    assert "{question_count}" in template


# ---------------------------------------------------------------------------
# 2. build_quiz_prompt() includes the contract values in the rendered prompt
# ---------------------------------------------------------------------------


def test_build_quiz_prompt_includes_contract_values() -> None:
    """All three contract values must appear in the rendered prompt."""
    from app.agents.quiz import build_quiz_prompt

    prompt = build_quiz_prompt(
        course_name="操作系统",
        question_count=5,
        question_types=["choice", "short_answer"],
        difficulty_distribution={"easy": 1, "medium": 3, "hard": 1},
        retrieved_chunks="[evidence_id=1 page=1] 示例资料",
        knowledge_points="[知识点1] kp_id=kp_1 标题=快表 TLB",
    )
    # question_count propagated into the prompt text.
    assert "5" in prompt
    # question_types propagated.
    assert "choice" in prompt
    assert "short_answer" in prompt
    # difficulty_distribution propagated as explicit counts.
    assert "1 easy" in prompt
    assert "3 medium" in prompt
    assert "1 hard" in prompt


# ---------------------------------------------------------------------------
# 3. API endpoint POST /quizzes passes parameters through to the prompt builder
# ---------------------------------------------------------------------------


def test_api_passes_contract_through_to_generate_quiz(
    client, tmp_path, monkeypatch
) -> None:
    """The endpoint must forward question_types / difficulty_distribution to
    generate_quiz (which builds the prompt)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    headers = auth_headers(client, username="contract-prop")
    course_id = _setup_course_with_kps(client, headers)

    captured: dict = {}

    def fake_generate_quiz(**kwargs):
        captured.update(kwargs)
        # Return exactly question_count items that satisfy the strict
        # QuizCreationService contract (count, types, difficulty) so the
        # endpoint returns 200 and we can inspect the forwarded kwargs.
        count = kwargs.get("question_count", 1)
        return {
            "title": "contract quiz",
            "items": [
                {
                    "question_type": "true_false",
                    "question_text": f"q{i}",
                    "options": [],
                    "answer": "true",
                    "explanation": "",
                    "knowledge_point_id": None,
                    "order_index": i,
                    "source_evidence_ids": [],
                    "source_evidence": [],
                    "rubric": [],
                    "difficulty": 1,
                    "verification_status": "verified",
                }
                for i in range(count)
            ],
        }

    monkeypatch.setattr(
        "app.services.quiz_creation_service.generate_quiz", fake_generate_quiz
    )

    resp = client.post(
        "/api/v1/quizzes",
        json={
            "course_id": course_id,
            "question_count": 2,
            "question_types": ["true_false"],
            "difficulty_distribution": {"easy": 2, "medium": 0, "hard": 0},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured.get("question_types") == ["true_false"]
    assert captured.get("difficulty_distribution") == {
        "easy": 2,
        "medium": 0,
        "hard": 0,
    }


# ---------------------------------------------------------------------------
# 4. Single question type -> prompt explicitly says only that type
# ---------------------------------------------------------------------------


def test_build_quiz_prompt_single_type_says_only_true_false() -> None:
    """When only true_false is requested, the prompt must restrict the LLM
    to generating true_false questions only."""
    from app.agents.quiz import build_quiz_prompt

    prompt = build_quiz_prompt(
        course_name="操作系统",
        question_count=3,
        question_types=["true_false"],
        difficulty_distribution=None,
        retrieved_chunks="",
        knowledge_points="",
    )
    assert "true_false" in prompt
    # The prompt must explicitly restrict generation to this type only.
    assert "仅生成" in prompt


# ---------------------------------------------------------------------------
# 5. Difficulty distribution appears verbatim in the prompt
# ---------------------------------------------------------------------------


def test_build_quiz_prompt_difficulty_distribution_verbatim() -> None:
    """The exact difficulty counts must appear in the prompt text."""
    from app.agents.quiz import build_quiz_prompt

    prompt = build_quiz_prompt(
        course_name="操作系统",
        question_count=3,
        question_types=None,
        difficulty_distribution={"easy": 2, "medium": 1, "hard": 0},
        retrieved_chunks="",
        knowledge_points="",
    )
    assert "2 easy, 1 medium, 0 hard" in prompt


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _setup_course_with_kps(client, headers, content=None, name="操作系统") -> int:
    """Create course + material + generate knowledge points.

    Returns the course_id ready for quiz generation.
    """
    course_id, _ = setup_course_with_material(
        client, headers, name=name, content=content
    )
    resp = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return course_id
