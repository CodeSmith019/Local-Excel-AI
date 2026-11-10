"""Node implementations for the LangGraph spreadsheet agent."""

import logging
from typing import Any, Literal

import pydantic
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from pydantic import BaseModel, ValidationError

from backend.agent.state import AgentState
from backend.config import get_settings
from backend.excel.a1 import bounding_range, parse_cell, parse_range
from backend.excel.adapter import (
    ExcelNotConnectedError,
    OpError,
    TargetError,
    WorkbookAdapter,
)
from backend.excel.com_thread import com_thread
from backend.excel.serializer import snapshot_to_prompt
from backend.excel.values import display_value
from backend.llm.client import structured_call
from backend.llm.prompts import load_prompt
from backend.ops.registry import REGISTRY, execute, implemented_ops
from backend.schemas.patch import Patch
from backend.schemas.sheet import SheetSnapshot
from backend.storage.undo import save_snapshot

logger = logging.getLogger(__name__)


def _resolve_adapter(config: RunnableConfig | None) -> WorkbookAdapter:
    """Retrieve workbook adapter from runnable config or default to XlwingsAdapter."""
    if config:
        configurable = config.get("configurable", {})
        adapter = configurable.get("adapter")
        if adapter is not None:
            return adapter

    from backend.excel.xlwings_adapter import XlwingsAdapter

    return XlwingsAdapter()


def _get_dynamic_intent_model() -> type[BaseModel]:
    """Dynamically construct IntentChoice Pydantic model with registered op IDs."""
    implemented = [spec.name for spec in implemented_ops()]
    valid_ops = tuple(implemented + ["unsupported"])
    op_literal = Literal[valid_ops]  # type: ignore[valid-type]
    return pydantic.create_model(
        "DynamicIntentChoice",
        op=(op_literal, ...),
        explanation=(str, ...),
    )


def _format_implemented_ops() -> str:
    """Format implemented operations for the classification prompt."""
    lines: list[str] = []
    for spec in implemented_ops():
        examples_str = "; ".join(f'"{ex}"' for ex in spec.examples)
        lines.append(
            f"- **{spec.name}** ({spec.title}): {spec.description}. Examples: {examples_str}"
        )
    return "\n".join(lines)


async def read_sheet(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Read the active sheet snapshot and serialize to prompt text."""
    adapter = _resolve_adapter(config)
    try:
        snapshot = await com_thread.run(adapter.read_snapshot)
    except ExcelNotConnectedError as exc:
        return {"error": str(exc), "applied": False}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed reading sheet snapshot: %s", exc)
        return {"error": f"Failed to read sheet: {exc}", "applied": False}

    settings = get_settings()
    sheet_text = snapshot_to_prompt(snapshot, max_rows=settings.max_prompt_rows)
    return {
        "snapshot": snapshot.model_dump(),
        "sheet_text": sheet_text,
        "error": None,
    }


async def classify_intent(state: AgentState) -> dict[str, Any]:
    """Classify the user's intent into an operation ID or 'unsupported'."""
    intent_model = _get_dynamic_intent_model()
    ops_text = _format_implemented_ops()
    sheet_text = state.get("sheet_text", "")
    user_instruction = state.get("user_message", "")

    prompt = load_prompt(
        "classify_intent",
        operations=ops_text,
        sheet_text=sheet_text,
        user_instruction=user_instruction,
    )

    result = await structured_call(
        intent_model,
        system_prompt=prompt,
        user_prompt=user_instruction,
    )

    if result.error or result.value is None:
        return {"error": result.error or "Failed to classify user intent"}

    return {
        "op": result.value.op,
        "op_explanation": result.value.explanation,
    }


async def extract_params(state: AgentState) -> dict[str, Any]:
    """Extract validated parameters for the chosen operation."""
    op_name = state.get("op")
    if not op_name or op_name not in REGISTRY:
        return {"error": f"Unknown operation '{op_name}'"}

    spec = REGISTRY[op_name]
    val_errors = state.get("validation_errors") or []
    current_retries = state.get("retries", 0)

    if val_errors:
        current_retries += 1
        errors_text = "\n".join(f"- {e}" for e in val_errors)
        validation_section = (
            f"\n# Previous Validation Errors\n{errors_text}\nPlease fix these errors.\n"
        )
    else:
        validation_section = ""

    prompt = load_prompt(
        spec.prompt_name,
        op_name=spec.name,
        op_title=spec.title,
        op_description=spec.description,
        sheet_text=state.get("sheet_text", ""),
        user_instruction=state.get("user_message", ""),
        validation_errors=validation_section,
    )

    result = await structured_call(
        spec.params_model,
        system_prompt=prompt,
        user_prompt=state.get("user_message", ""),
    )

    if result.error or result.value is None:
        return {
            "retries": current_retries,
            "validation_errors": [result.error or "Failed to extract parameters"],
        }

    return {
        "params": result.value.model_dump(),
        "retries": current_retries,
        "validation_errors": [],
    }


async def execute_op(state: AgentState) -> dict[str, Any]:
    """Execute the operation on the snapshot and generate a Patch."""
    if state.get("validation_errors"):
        return {}

    op_name = state.get("op")
    if not op_name or op_name not in REGISTRY:
        return {"validation_errors": [f"Unknown operation: {op_name}"]}

    snapshot_dict = state.get("snapshot")
    if not snapshot_dict:
        return {"validation_errors": ["No sheet snapshot available"]}

    params_dict = state.get("params")
    if params_dict is None:
        return {"validation_errors": ["No parameters extracted"]}

    try:
        snapshot = SheetSnapshot.model_validate(snapshot_dict)
        patch = execute(op_name, snapshot, params_dict)
        return {"patch": patch.model_dump(), "validation_errors": []}
    except (TargetError, OpError, ValidationError) as exc:
        return {"validation_errors": [str(exc)]}
    except Exception as exc:  # noqa: BLE001
        return {"validation_errors": [f"Operation error: {exc}"]}


async def validate(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Validate bounding range and run custom operation validator if present."""
    patch_dict = state.get("patch") or {}
    patch = Patch.model_validate(patch_dict)

    snapshot_dict = state.get("snapshot") or {}
    snapshot = SheetSnapshot.model_validate(snapshot_dict)

    errors: list[str] = []

    spec = REGISTRY.get(patch.op)
    if spec and spec.validator is not None:
        adapter = _resolve_adapter(config)
        params_dict = state.get("params") or {}
        params = spec.params_model.model_validate(params_dict)
        val_errors, updated_patch = await spec.validator(snapshot, params, patch, adapter)
        errors.extend(val_errors)
        patch = updated_patch

    if errors:
        return {"validation_errors": errors}

    if not patch.cells and not patch.formats:
        return {}

    _r1, _c1, r2, c2 = parse_range(snapshot.used_range)
    max_allowed_r = r2 + 3
    max_allowed_c = c2 + 2

    addrs = [c.address for c in patch.cells] + [f.address for f in patch.formats]
    for addr in addrs:
        r, c = parse_cell(addr)
        if not (1 <= r <= max_allowed_r and 1 <= c <= max_allowed_c):
            errors.append(
                f"Address {addr} is outside allowed range "
                f"(max row {max_allowed_r}, max col {max_allowed_c})"
            )

    if errors:
        return {"validation_errors": errors}

    return {"patch": patch.model_dump(), "validation_errors": []}


async def preview(state: AgentState) -> dict[str, Any]:
    """Build preview payload and interrupt execution awaiting user approval.

    This node re-runs from the beginning when resumed, so it must not have
    side effects prior to interrupt().
    """
    patch_dict = state.get("patch") or {}
    patch = Patch.model_validate(patch_dict)

    changes: list[dict[str, Any]] = []
    for cell in patch.cells[:200]:
        val = patch.preview_values.get(cell.address)
        changes.append(
            {
                "address": cell.address,
                "before": display_value(cell.before),
                "after": display_value(cell.after) if cell.after_formula is None else None,
                "formula": cell.after_formula,
                "value": display_value(val) if val is not None else None,
            }
        )

    formats = [
        {"address": fmt.address, "fill_hex": fmt.fill_hex} for fmt in patch.formats[:200]
    ]

    payload = {
        "thread_id": state.get("thread_id", ""),
        "op": patch.op,
        "summary": patch.summary,
        "changes": changes,
        "formats": formats,
        "warnings": patch.warnings,
    }

    resume_val = interrupt(payload)

    approved = False
    if isinstance(resume_val, dict):
        approved = bool(resume_val.get("approved", False))
    elif isinstance(resume_val, bool):
        approved = resume_val

    return {"approved": approved}


async def apply_patch(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Re-verify cell values, save undo snapshot, and apply patch to the sheet."""
    patch_dict = state.get("patch") or {}
    patch = Patch.model_validate(patch_dict)
    adapter = _resolve_adapter(config)

    addrs = [c.address for c in patch.cells] + [f.address for f in patch.formats]
    if not addrs:
        return {"applied": False, "result_summary": "Nothing to change"}

    region = bounding_range(addrs)
    r1, c1, _r2, _c2 = parse_range(region)

    current_region = await com_thread.run(adapter.read_region, region)

    for cell in patch.cells:
        row, col = parse_cell(cell.address)
        row_idx = row - r1
        col_idx = col - c1
        current_val = current_region.values[row_idx][col_idx]
        if current_val != cell.before:
            err_msg = "The sheet changed since the preview - please ask again."
            return {"error": err_msg, "applied": False, "result_summary": err_msg}

    # Save undo snapshot before applying patch
    save_snapshot(
        thread_id=state.get("thread_id"),
        state=current_region,
        summary=patch.summary,
    )

    await com_thread.run(adapter.apply_patch, patch)

    return {
        "applied": True,
        "result_summary": patch.summary,
        "error": None,
    }


async def finish_unsupported(state: AgentState) -> dict[str, Any]:
    """Finish when requested operation is not supported."""
    titles = [spec.title for spec in implemented_ops()]
    titles_str = ", ".join(titles)
    summary = f"I cannot do that yet. Here is what I can do: {titles_str}."
    return {"applied": False, "result_summary": summary}


async def finish_error(state: AgentState) -> dict[str, Any]:
    """Finish when an unrecoverable error or retry exhaustion occurred."""
    err = state.get("error")
    if not err:
        val_errors = state.get("validation_errors") or []
        err = "; ".join(val_errors) if val_errors else "An error occurred."
    return {"applied": False, "error": err, "result_summary": err}


async def finish_nothing(state: AgentState) -> dict[str, Any]:
    """Finish when no changes were needed."""
    return {"applied": False, "result_summary": "Nothing to change"}


async def finish_cancelled(state: AgentState) -> dict[str, Any]:
    """Finish when user rejected preview."""
    return {"applied": False, "result_summary": "Operation cancelled"}

