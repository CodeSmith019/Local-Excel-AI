"""Prompt template loader for LLM system and user prompts."""

from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str, /, **variables: Any) -> str:
    """Load a markdown prompt template and substitute variables using str.format_map.

    Templates live under backend/llm/prompts/{name}.md. Placeholders are written
    as {placeholder_name} and literal braces are escaped as {{ or }}.

    Args:
        name: Name of the prompt file without .md extension (positional-only).
        **variables: Keyword arguments providing values for template placeholders.

    Returns:
        The formatted prompt text as a string.

    Raises:
        FileNotFoundError: If the template file does not exist.
        KeyError: If a required placeholder variable is missing from kwargs.
    """
    prompt_path = PROMPTS_DIR / f"{name}.md"
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt template '{name}' not found at {prompt_path}")

    content = prompt_path.read_text(encoding="utf-8")

    try:
        return content.format_map(variables)
    except KeyError as exc:
        missing_var = exc.args[0]
        raise KeyError(
            f"Missing required variable '{missing_var}' in prompt template '{name}'"
        ) from exc
