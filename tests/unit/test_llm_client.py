"""Unit tests for backend.llm.client module."""

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import BaseModel

import backend.llm.client as client_module
from backend.llm.client import get_chat_model, structured_call


class DummyFormula(BaseModel):
    """Test schema for structured output."""

    formula: str
    explanation: str


class FakeStructuredRunnable:
    """Fake runnable for with_structured_output."""

    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[list[Any]] = []

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> dict[str, Any]:
        self.calls.append(messages)
        if not self.responses:
            raise RuntimeError("FakeStructuredRunnable ran out of responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakeChatModel:
    """Fake ChatOpenAI model tracking with_structured_output calls."""

    def __init__(self, runnable: FakeStructuredRunnable) -> None:
        self.runnable = runnable
        self.structured_calls: list[tuple[Any, str, bool]] = []

    def with_structured_output(
        self,
        schema: Any,
        method: str = "json_schema",
        include_raw: bool = True,
    ) -> FakeStructuredRunnable:
        self.structured_calls.append((schema, method, include_raw))
        return self.runnable


@pytest.fixture(autouse=True)
def reset_preferred_method() -> None:
    """Reset preferred structured output method before each test."""
    client_module._preferred_method = "json_schema"


def test_get_chat_model_cached() -> None:
    """Test that get_chat_model returns a cached instance with expected configuration."""
    model1 = get_chat_model()
    model2 = get_chat_model()
    assert model1 is model2
    assert model1.openai_api_key.get_secret_value() == "sk-local"
    assert model1.max_retries == 0


async def test_structured_call_success_first_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful structured call on the first attempt."""
    mock_raw = MagicMock()
    mock_raw.content = '{"formula": "=D2*E2", "explanation": "Multiplies D2 by E2"}'
    mock_raw.usage_metadata = {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
    expected_obj = DummyFormula(formula="=D2*E2", explanation="Multiplies D2 by E2")

    runnable = FakeStructuredRunnable(
        responses=[{"raw": mock_raw, "parsed": expected_obj, "parsing_error": None}]
    )
    fake_model = FakeChatModel(runnable)
    monkeypatch.setattr(client_module, "get_chat_model", lambda: fake_model)

    res = await structured_call(DummyFormula, "System prompt", "User prompt")

    assert res.value == expected_obj
    assert res.error is None
    assert res.raw_text == mock_raw.content
    assert res.latency_ms >= 0
    assert res.usage == mock_raw.usage_metadata
    assert len(runnable.calls) == 1


async def test_structured_call_retry_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test invalid first answer followed by valid second answer (retry succeeds)."""
    mock_raw1 = MagicMock()
    mock_raw1.content = '{"formula": "=D2"}'
    mock_raw2 = MagicMock()
    mock_raw2.content = '{"formula": "=D2*E2", "explanation": "Fixed"}'
    expected_obj = DummyFormula(formula="=D2*E2", explanation="Fixed")

    runnable = FakeStructuredRunnable(
        responses=[
            {
                "raw": mock_raw1,
                "parsed": None,
                "parsing_error": "ValidationError: explanation is missing",
            },
            {
                "raw": mock_raw2,
                "parsed": expected_obj,
                "parsing_error": None,
            },
        ]
    )
    fake_model = FakeChatModel(runnable)
    monkeypatch.setattr(client_module, "get_chat_model", lambda: fake_model)

    res = await structured_call(DummyFormula, "System prompt", "User prompt")

    assert res.value == expected_obj
    assert res.error is None
    assert len(runnable.calls) == 2

    # Check retry message formatting
    retry_user_msg = runnable.calls[1][1].content
    assert "Your previous answer was invalid: ValidationError: explanation is missing." in retry_user_msg
    assert "Return only valid JSON." in retry_user_msg


async def test_structured_call_invalid_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test invalid answer on both first attempt and retry."""
    mock_raw1 = MagicMock()
    mock_raw1.content = "bad 1"
    mock_raw2 = MagicMock()
    mock_raw2.content = "bad 2"

    runnable = FakeStructuredRunnable(
        responses=[
            {"raw": mock_raw1, "parsed": None, "parsing_error": "Error 1"},
            {"raw": mock_raw2, "parsed": None, "parsing_error": "Error 2"},
        ]
    )
    fake_model = FakeChatModel(runnable)
    monkeypatch.setattr(client_module, "get_chat_model", lambda: fake_model)

    res = await structured_call(DummyFormula, "System prompt", "User prompt")

    assert res.value is None
    assert res.error is not None
    assert "Validation failed after retry: Error 2" in res.error
    assert len(runnable.calls) == 2


async def test_structured_call_exception_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that model/network exceptions are caught and stored in .error."""
    runnable = FakeStructuredRunnable(
        responses=[httpx.ConnectError("Connection refused to llama-server")]
    )
    fake_model = FakeChatModel(runnable)
    monkeypatch.setattr(client_module, "get_chat_model", lambda: fake_model)

    res = await structured_call(DummyFormula, "System prompt", "User prompt")

    assert res.value is None
    assert res.error is not None
    assert "ConnectError" in res.error
    assert "Connection refused" in res.error
    assert res.latency_ms >= 0


async def test_structured_call_json_mode_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test fallback to method='json_mode' when method='json_schema' is rejected."""
    mock_raw = MagicMock()
    mock_raw.content = '{"formula": "=SUM(A1:A10)", "explanation": "Sum"}'
    expected_obj = DummyFormula(formula="=SUM(A1:A10)", explanation="Sum")

    # First call raises a 400 Bad Request regarding json_schema
    # Second call (with json_mode) returns successfully
    runnable = FakeStructuredRunnable(
        responses=[
            RuntimeError("400 Bad Request: response_format json_schema not supported"),
            {"raw": mock_raw, "parsed": expected_obj, "parsing_error": None},
        ]
    )
    fake_model = FakeChatModel(runnable)
    monkeypatch.setattr(client_module, "get_chat_model", lambda: fake_model)

    res = await structured_call(DummyFormula, "System prompt", "User prompt")

    assert res.value == expected_obj
    assert res.error is None
    # Verify method fallback occurred
    assert fake_model.structured_calls[0][1] == "json_schema"
    assert fake_model.structured_calls[1][1] == "json_mode"
    assert client_module._preferred_method == "json_mode"

