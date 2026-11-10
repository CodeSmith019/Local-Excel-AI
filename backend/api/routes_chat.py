"""SSE streaming chat and confirmation endpoints."""

import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from langgraph.types import Command
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from backend.api.deps import get_adapter, get_graph
from backend.ops.registry import REGISTRY
from backend.schemas.api import ChatRequest, ConfirmRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

NODE_LABELS: dict[str, str] = {
    "read_sheet": "Reading sheet",
    "classify_intent": "Understanding request",
    "extract_params": "Working out details",
    "execute_op": "Preparing changes",
    "validate": "Checking changes",
    "apply_patch": "Applying changes",
}


@router.post("/chat")
async def chat_endpoint(
    request: Request,
    req: ChatRequest,
) -> EventSourceResponse:
    """Start or continue a chat session with SSE streaming."""
    graph = get_graph(request)
    adapter = get_adapter(request)
    tid = req.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": tid, "adapter": adapter}}
    initial_state = {
        "thread_id": tid,
        "user_message": req.message,
        "retries": 0,
        "validation_errors": [],
    }

    async def event_generator() -> AsyncGenerator[ServerSentEvent, None]:
        node_start_time = time.perf_counter()
        try:
            interrupted = False
            async for chunk in graph.astream(
                initial_state, config=config, stream_mode="updates"
            ):
                now = time.perf_counter()
                latency_ms = (now - node_start_time) * 1000.0
                node_start_time = now

                if "__interrupt__" in chunk:
                    interrupted = True
                    interrupt_info = chunk["__interrupt__"][0]
                    payload = (
                        interrupt_info.value
                        if hasattr(interrupt_info, "value")
                        else interrupt_info
                    )
                    yield ServerSentEvent(data=json.dumps(payload), event="preview")
                    break

                for node_name, node_update in chunk.items():
                    logger.info("Node '%s' completed in %.2f ms", node_name, latency_ms)
                    if node_name in NODE_LABELS:
                        yield ServerSentEvent(
                            data=json.dumps(
                                {"node": node_name, "label": NODE_LABELS[node_name]}
                            ),
                            event="status",
                        )

                    if node_name == "extract_params" and isinstance(node_update, dict):
                        state_snap = await graph.aget_state(config)
                        state_vals = state_snap.values
                        op = state_vals.get("op", "")
                        spec = REGISTRY.get(op)
                        op_title = spec.title if spec else op
                        plan_payload = {
                            "op": op,
                            "op_title": op_title,
                            "params": state_vals.get("params"),
                            "explanation": state_vals.get("op_explanation", ""),
                        }
                        yield ServerSentEvent(data=json.dumps(plan_payload), event="plan")

            if not interrupted:
                state_snap = await graph.aget_state(config)
                state_vals = state_snap.values
                if state_vals.get("error"):
                    yield ServerSentEvent(
                        data=json.dumps({"message": state_vals["error"]}),
                        event="error",
                    )
                else:
                    yield ServerSentEvent(
                        data=json.dumps(
                            {
                                "applied": state_vals.get("applied", False),
                                "summary": state_vals.get("result_summary", ""),
                            }
                        ),
                        event="done",
                    )
        except Exception as exc:
            logger.exception("Error in chat event stream")
            yield ServerSentEvent(data=json.dumps({"message": str(exc)}), event="error")

    return EventSourceResponse(event_generator())


@router.post("/confirm")
async def confirm_endpoint(
    request: Request,
    req: ConfirmRequest,
) -> EventSourceResponse:
    """Confirm or reject a previewed patch via SSE streaming."""
    graph = get_graph(request)
    adapter = get_adapter(request)
    tid = req.thread_id
    config = {"configurable": {"thread_id": tid, "adapter": adapter}}
    resume_cmd = Command(resume={"approved": req.approved})

    async def event_generator() -> AsyncGenerator[ServerSentEvent, None]:
        node_start_time = time.perf_counter()
        try:
            async for chunk in graph.astream(
                resume_cmd, config=config, stream_mode="updates"
            ):
                now = time.perf_counter()
                latency_ms = (now - node_start_time) * 1000.0
                node_start_time = now

                if "__interrupt__" in chunk:
                    interrupt_info = chunk["__interrupt__"][0]
                    payload = (
                        interrupt_info.value
                        if hasattr(interrupt_info, "value")
                        else interrupt_info
                    )
                    yield ServerSentEvent(data=json.dumps(payload), event="preview")
                    continue

                for node_name in chunk:
                    logger.info("Node '%s' completed in %.2f ms", node_name, latency_ms)
                    if node_name in NODE_LABELS:
                        yield ServerSentEvent(
                            data=json.dumps(
                                {"node": node_name, "label": NODE_LABELS[node_name]}
                            ),
                            event="status",
                        )

            state_snap = await graph.aget_state(config)
            state_vals = state_snap.values
            if state_vals.get("error"):
                yield ServerSentEvent(
                    data=json.dumps({"message": state_vals["error"]}),
                    event="error",
                )
            else:
                yield ServerSentEvent(
                    data=json.dumps(
                        {
                            "applied": state_vals.get("applied", False),
                            "summary": state_vals.get("result_summary", ""),
                        }
                    ),
                    event="done",
                )
        except Exception as exc:
            logger.exception("Error in confirm event stream")
            yield ServerSentEvent(data=json.dumps({"message": str(exc)}), event="error")

    return EventSourceResponse(event_generator())
