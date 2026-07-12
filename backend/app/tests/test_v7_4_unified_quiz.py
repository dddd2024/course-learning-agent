"""V7.4-03 P0-03: Quiz creation must use QuizCreationService for all paths.

Tests that the POST /quizzes endpoint delegates to QuizCreationService
and does NOT call generate_quiz directly.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))


def test_quiz_endpoint_calls_quiz_creation_service():
    """POST /quizzes endpoint must call QuizCreationService.create_quiz."""
    from app.api.v1.endpoints import quizzes as quizzes_mod

    source = inspect.getsource(quizzes_mod)
    assert "QuizCreationService.create_quiz" in source, (
        "Endpoint module does not call QuizCreationService.create_quiz"
    )


def test_quiz_endpoint_does_not_call_generate_quiz_directly():
    """The create_quiz endpoint function must not call generate_quiz() directly."""
    from app.api.v1.endpoints import quizzes as quizzes_mod

    source = inspect.getsource(quizzes_mod)
    # Find the create_quiz endpoint function
    lines = source.split("\n")
    in_create_endpoint = False
    endpoint_lines = []
    brace_depth = 0
    for line in lines:
        if "def create_quiz(" in line:
            in_create_endpoint = True
        if in_create_endpoint:
            endpoint_lines.append(line)
            # End at the next function definition at the same indent level
            if len(endpoint_lines) > 3 and line.startswith("def ") and "def create_quiz(" not in line:
                break

    endpoint_source = "\n".join(endpoint_lines)
    # The endpoint should NOT call generate_quiz directly
    # (QuizCreationService calls it internally)
    direct_calls = [
        line for line in endpoint_lines
        if "generate_quiz(" in line and "QuizCreationService" not in line and "import" not in line
    ]
    assert len(direct_calls) == 0, (
        f"Endpoint calls generate_quiz directly instead of QuizCreationService: {direct_calls}"
    )


def test_quiz_creation_service_imported_in_endpoint():
    """QuizCreationService must be imported in the quizzes endpoint module."""
    from app.api.v1.endpoints import quizzes as quizzes_mod

    source = inspect.getsource(quizzes_mod)
    assert "from app.services.quiz_creation_service import QuizCreationService" in source or \
           "import QuizCreationService" in source, (
        "QuizCreationService is not imported in the endpoint module"
    )
