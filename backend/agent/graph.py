"""LangGraph agent graph definition and construction."""

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.agent.nodes import (
    apply_patch,
    classify_intent,
    execute_op,
    extract_params,
    finish_cancelled,
    finish_error,
    finish_nothing,
    finish_unsupported,
    preview,
    read_sheet,
    validate,
)
from backend.agent.state import AgentState
from backend.config import get_settings


def route_read_sheet(state: AgentState) -> str:
    """Route from read_sheet based on connection success or error."""
    if state.get("error"):
        return "finish_error"
    return "classify_intent"


def route_classify_intent(state: AgentState) -> str:
    """Route from classify_intent based on chosen operation."""
    if state.get("error"):
        return "finish_error"
    if state.get("op") == "unsupported":
        return "finish_unsupported"
    return "extract_params"


def route_execute_op(state: AgentState) -> str:
    """Route from execute_op to validate or retry extraction on error."""
    if state.get("validation_errors"):
        settings = get_settings()
        if state.get("retries", 0) < settings.max_retries:
            return "extract_params"
        return "finish_error"
    return "validate"


def route_validate(state: AgentState) -> str:
    """Route from validate to retry, finish_nothing, or preview."""
    if state.get("validation_errors"):
        settings = get_settings()
        if any("merged cells" in err.lower() for err in state.get("validation_errors", [])):
            return "finish_error"
        if state.get("retries", 0) < settings.max_retries:
            return "extract_params"
        return "finish_error"

    patch_dict = state.get("patch") or {}
    cells = patch_dict.get("cells") or []
    formats = patch_dict.get("formats") or []
    if not cells and not formats:
        return "finish_nothing"

    return "preview"


def route_preview(state: AgentState) -> str:
    """Route from preview based on user approval."""
    if state.get("approved"):
        return "apply_patch"
    return "finish_cancelled"


def build_graph(checkpointer: Any = None) -> CompiledStateGraph:
    """Construct and compile the Excel AI LangGraph agent graph.

    Follows the exact architecture specified in PROJECT_CONTEXT.md section 3.
    """
    builder = StateGraph(AgentState)

    # Register nodes
    builder.add_node("read_sheet", read_sheet)
    builder.add_node("classify_intent", classify_intent)
    builder.add_node("extract_params", extract_params)
    builder.add_node("execute_op", execute_op)
    builder.add_node("validate", validate)
    builder.add_node("preview", preview)
    builder.add_node("apply_patch", apply_patch)
    builder.add_node("finish_unsupported", finish_unsupported)
    builder.add_node("finish_error", finish_error)
    builder.add_node("finish_nothing", finish_nothing)
    builder.add_node("finish_cancelled", finish_cancelled)

    # Flow edges
    builder.add_edge(START, "read_sheet")

    builder.add_conditional_edges(
        "read_sheet",
        route_read_sheet,
        {
            "finish_error": "finish_error",
            "classify_intent": "classify_intent",
        },
    )

    builder.add_conditional_edges(
        "classify_intent",
        route_classify_intent,
        {
            "finish_error": "finish_error",
            "finish_unsupported": "finish_unsupported",
            "extract_params": "extract_params",
        },
    )

    builder.add_edge("extract_params", "execute_op")

    builder.add_conditional_edges(
        "execute_op",
        route_execute_op,
        {
            "extract_params": "extract_params",
            "finish_error": "finish_error",
            "validate": "validate",
        },
    )

    builder.add_conditional_edges(
        "validate",
        route_validate,
        {
            "extract_params": "extract_params",
            "finish_error": "finish_error",
            "finish_nothing": "finish_nothing",
            "preview": "preview",
        },
    )

    builder.add_conditional_edges(
        "preview",
        route_preview,
        {
            "apply_patch": "apply_patch",
            "finish_cancelled": "finish_cancelled",
        },
    )

    builder.add_edge("apply_patch", END)
    builder.add_edge("finish_unsupported", END)
    builder.add_edge("finish_error", END)
    builder.add_edge("finish_nothing", END)
    builder.add_edge("finish_cancelled", END)

    return builder.compile(checkpointer=checkpointer)

