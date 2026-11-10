"""Unit tests for backend.llm.prompts module."""

from pathlib import Path

import pytest

from backend.llm.prompts import load_prompt


def test_load_and_fill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading a template and filling placeholders."""
    template_content = "Hello {name}, your role is {role}."
    test_file = tmp_path / "greeting.md"
    test_file.write_text(template_content, encoding="utf-8")

    monkeypatch.setattr("backend.llm.prompts.PROMPTS_DIR", tmp_path)

    result = load_prompt("greeting", name="Alice", role="Engineer")
    assert result == "Hello Alice, your role is Engineer."


def test_missing_variable_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that missing variables raise KeyError naming the template and variable."""
    template_content = "Hello {name}, your code is {code}."
    test_file = tmp_path / "user_info.md"
    test_file.write_text(template_content, encoding="utf-8")

    monkeypatch.setattr("backend.llm.prompts.PROMPTS_DIR", tmp_path)

    with pytest.raises(KeyError) as exc_info:
        load_prompt("user_info", name="Bob")

    error_msg = str(exc_info.value)
    assert "user_info" in error_msg
    assert "code" in error_msg


def test_escaped_braces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that literal braces written as {{ }} are preserved as { }."""
    template_content = "Formula: {{=SUM(A1:A10)}} for user {user}."
    test_file = tmp_path / "formula_info.md"
    test_file.write_text(template_content, encoding="utf-8")

    monkeypatch.setattr("backend.llm.prompts.PROMPTS_DIR", tmp_path)

    result = load_prompt("formula_info", user="Charlie")
    assert result == "Formula: {=SUM(A1:A10)} for user Charlie."


def test_template_not_found() -> None:
    """Test that non-existent templates raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError) as exc_info:
        load_prompt("non_existent_template_xyz123")

    assert "non_existent_template_xyz123" in str(exc_info.value)


def test_load_smoke_test_template() -> None:
    """Test loading the real smoke_test.md prompt template."""
    content = load_prompt("smoke_test")
    assert "Excel formula" in content
    assert "JSON" in content
