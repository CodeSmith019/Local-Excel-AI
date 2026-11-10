"""FastAPI dependencies."""

from fastapi import Request
from langgraph.graph.state import CompiledStateGraph

from backend.excel.adapter import WorkbookAdapter


def get_adapter(request: Request) -> WorkbookAdapter:
    """Retrieve the workbook adapter instance stored on app.state."""
    return request.app.state.adapter


def get_graph(request: Request) -> CompiledStateGraph:
    """Retrieve the compiled LangGraph agent graph stored on app.state."""
    return request.app.state.graph
