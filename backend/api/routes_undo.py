"""Undo management API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Request

from backend.api.deps import get_adapter
from backend.excel.com_thread import com_thread
from backend.schemas.api import UndoResponse
from backend.storage.undo import list_recent, pop_latest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["undo"])


@router.post("/undo", response_model=UndoResponse)
async def undo_endpoint(
    request: Request,
) -> UndoResponse:
    """Pop the latest snapshot and restore it through the adapter."""
    adapter = get_adapter(request)
    popped = pop_latest()
    if popped is None:
        return UndoResponse(restored=False, summary="No changes to undo.")

    state, summary = popped
    await com_thread.run(adapter.restore_region, state)
    logger.info("Restored undo snapshot for region: %s", state.region)
    return UndoResponse(restored=True, summary=summary)


@router.get("/undo/history")
async def undo_history_endpoint() -> list[dict[str, Any]]:
    """Return the 10 most recent undo snapshot summaries."""
    return list_recent(10)
