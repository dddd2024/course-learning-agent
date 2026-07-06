"""Prompt template loader.

Loads versioned prompt templates from the ``prompts/`` directory next
to this module. Templates are named ``{agent_type}_{version}.md``.
"""
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(agent_type: str, version: str = "v1") -> str:
    """Return the contents of ``prompts/{agent_type}_{version}.md``.

    Raises FileNotFoundError if the template does not exist.
    """
    file_path = _PROMPTS_DIR / f"{agent_type}_{version}.md"
    return file_path.read_text(encoding="utf-8")
