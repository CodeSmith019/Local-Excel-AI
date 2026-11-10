"""LLM client and structured output call helper."""

import json
import logging
import time
from functools import lru_cache
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from backend.config import get_settings

logger = logging.getLogger(__name__)

# Tracks preferred structured output method: "json_schema" or "json_mode"
_preferred_method: str = "json_schema"


class StructuredResult[T: BaseModel](BaseModel):
    """Generic container for structured LLM call results."""

    value: T | None = None
    raw_text: str = ""
    error: str | None = None
    latency_ms: float = 0.0
    usage: dict[str, Any] = Field(default_factory=dict)


@lru_cache
def get_chat_model() -> ChatOpenAI:
    """Return cached ChatOpenAI instance configured from Settings."""
    settings = get_settings()
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key="sk-local",
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_s,
        max_retries=0,
        extra_body=settings.llm_extra_body or None,
    )


def _extract_raw_text(raw: Any) -> str:
    """Extract raw text string from LLM output."""
    if raw is None:
        return ""
    if hasattr(raw, "content"):
        content = raw.content
        return content if isinstance(content, str) else str(content)
    if isinstance(raw, dict):
        return str(raw.get("content", raw))
    return str(raw)


def _extract_usage(raw: Any) -> dict[str, Any]:
    """Extract token usage dictionary from LLM output."""
    if raw is None:
        return {}
    if hasattr(raw, "usage_metadata") and raw.usage_metadata:
        return dict(raw.usage_metadata)
    if hasattr(raw, "response_metadata") and isinstance(raw.response_metadata, dict):
        token_usage = raw.response_metadata.get("token_usage")
        if isinstance(token_usage, dict):
            return dict(token_usage)
    return {}


def _is_schema_rejection(exc: Exception) -> bool:
    """Check if exception indicates server rejection of method='json_schema'."""
    msg = str(exc).lower()
    return (
        "json_schema" in msg
        or "response_format" in msg
        or "bad request" in msg
        or "400" in msg
        or "unsupported" in msg
    )


async def structured_call[T: BaseModel](
    schema: type[T],
    system_prompt: str,
    user_prompt: str,
) -> StructuredResult[T]:
    """Call the LLM and return a validated Pydantic model instance.

    Uses ChatOpenAI.with_structured_output with method="json_schema", falling back
    to method="json_mode" if the local server rejects json_schema. If parsing fails,
    retries once with the validation error appended to the user prompt. Never raises
    for model or network errors; returns errors in StructuredResult.error.

    Args:
        schema: Target Pydantic model class to validate output against.
        system_prompt: System instructions for the model.
        user_prompt: User request or context for the model.

    Returns:
        StructuredResult containing the parsed value, raw text, error, latency, and usage.
    """
    global _preferred_method

    t0 = time.perf_counter()
    initial_chars = len(system_prompt) + len(user_prompt)

    logger.debug("LLM system prompt:\n%s", system_prompt)
    logger.debug("LLM user prompt:\n%s", user_prompt)

    model = get_chat_model()
    method = _preferred_method

    async def _execute_attempt(
        current_method: str,
        sys_p: str,
        usr_p: str,
    ) -> tuple[dict[str, Any], str]:
        """Configure runnable and invoke once with the given method and prompts."""
        logger.info("Using structured output method='%s'", current_method)
        if current_method == "json_mode":
            schema_json = json.dumps(schema.model_json_schema(), indent=2)
            sys_p = (
                f"{sys_p}\n\nYou must return a valid JSON object matching this schema:\n{schema_json}"
            )

        runnable = model.with_structured_output(schema, method=current_method, include_raw=True)
        messages = [SystemMessage(content=sys_p), HumanMessage(content=usr_p)]
        result = await runnable.ainvoke(messages)
        return result, sys_p

    try:
        # First attempt
        try:
            res1, active_sys_p = await _execute_attempt(method, system_prompt, user_prompt)
        except Exception as exc:
            if method == "json_schema" and _is_schema_rejection(exc):
                logger.warning(
                    "llama-server rejected method='json_schema' (%s); switching to method='json_mode'",
                    exc,
                )
                method = "json_mode"
                _preferred_method = "json_mode"
                res1, active_sys_p = await _execute_attempt(method, system_prompt, user_prompt)
            else:
                raise

        parsed1 = res1.get("parsed")
        parsing_error1 = res1.get("parsing_error")
        raw1 = res1.get("raw")
        raw_text1 = _extract_raw_text(raw1)
        usage1 = _extract_usage(raw1)

        # Success on first attempt
        if parsed1 is not None and parsing_error1 is None:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            logger.info(
                "LLM structured call ok (method=%s, prompt_chars=%d, latency=%.1fms)",
                method,
                initial_chars,
                latency_ms,
            )
            return StructuredResult[T](
                value=parsed1,
                raw_text=raw_text1,
                error=None,
                latency_ms=latency_ms,
                usage=usage1,
            )

        # First attempt failed parsing; retry ONCE with error message
        err_msg = str(parsing_error1) if parsing_error1 else "Parsed object is None"
        logger.warning("LLM structured output parsing failed on attempt 1: %s. Retrying...", err_msg)

        retry_user_prompt = (
            f"{user_prompt}\n\nYour previous answer was invalid: {err_msg}. Return only valid JSON."
        )
        logger.debug("LLM retry user prompt:\n%s", retry_user_prompt)

        res2, _ = await _execute_attempt(method, active_sys_p, retry_user_prompt)
        parsed2 = res2.get("parsed")
        parsing_error2 = res2.get("parsing_error")
        raw2 = res2.get("raw")
        raw_text2 = _extract_raw_text(raw2)
        usage2 = _extract_usage(raw2) or usage1

        latency_ms = (time.perf_counter() - t0) * 1000.0
        retry_chars = len(active_sys_p) + len(retry_user_prompt)

        if parsed2 is not None and parsing_error2 is None:
            logger.info(
                "LLM structured call ok on retry (method=%s, prompt_chars=%d, latency=%.1fms)",
                method,
                retry_chars,
                latency_ms,
            )
            return StructuredResult[T](
                value=parsed2,
                raw_text=raw_text2,
                error=None,
                latency_ms=latency_ms,
                usage=usage2,
            )

        final_err = str(parsing_error2) if parsing_error2 else "Validation failed after retry"
        logger.info(
            "LLM structured call error (method=%s, prompt_chars=%d, latency=%.1fms): %s",
            method,
            retry_chars,
            latency_ms,
            final_err,
        )
        return StructuredResult[T](
            value=None,
            raw_text=raw_text2,
            error=f"Validation failed after retry: {final_err}",
            latency_ms=latency_ms,
            usage=usage2,
        )

    except Exception as exc:  # noqa: BLE001 (spec: never raise for model/network errors)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        error_str = f"{type(exc).__name__}: {exc}"
        logger.info(
            "LLM structured call error (method=%s, prompt_chars=%d, latency=%.1fms): %s",
            method,
            initial_chars,
            latency_ms,
            error_str,
        )
        return StructuredResult[T](
            value=None,
            raw_text="",
            error=error_str,
            latency_ms=latency_ms,
            usage={},
        )
