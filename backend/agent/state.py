"""LangGraph agent state definition."""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """Execution state for the spreadsheet agent graph.

    All Pydantic objects are stored as model_dump() dictionaries to ensure
    serialization compatibility across checkpoints.
    """

    thread_id: str
    user_message: str
    snapshot: dict[str, Any] | None
    sheet_text: str
    op: str | None
    op_explanation: str
    params: dict[str, Any] | None
    patch: dict[str, Any] | None
    validation_errors: list[str]
    retries: int
    result_summary: str | None
    applied: bool
    error: str | None
    approved: bool

