"""Health check endpoint for backend, local LLM server, and Excel bridge."""

import logging

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.config import get_settings
from backend.excel.com_thread import com_thread

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class LlmHealth(BaseModel):
    """Health status of the local LLM server."""

    reachable: bool
    model: str | None = None
    error: str | None = None


class ExcelHealth(BaseModel):
    """Health status of the Excel bridge."""

    connected: bool
    workbook: str | None = None
    sheet: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    """Health check response schema."""

    backend: str
    machine: str
    llm: LlmHealth
    excel: ExcelHealth


@router.get("/health", response_model=HealthResponse)
async def check_health(request: Request) -> HealthResponse:
    """Check health of backend, local LLM server, and Excel connection."""
    settings = get_settings()
    url = f"{settings.llm_base_url.rstrip('/')}/models"

    reachable = False
    model_name: str | None = None
    error_msg: str | None = None

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                model_list = data.get("data") or data.get("models")
                if isinstance(model_list, list) and len(model_list) > 0:
                    first_model = model_list[0]
                    model_name = (
                        first_model.get("id")
                        if isinstance(first_model, dict)
                        else str(first_model)
                    )
            elif isinstance(data, list) and len(data) > 0:
                first_model = data[0]
                model_name = (
                    first_model.get("id")
                    if isinstance(first_model, dict)
                    else str(first_model)
                )
            if not model_name:
                model_name = settings.llm_model
            reachable = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM server unreachable at %s: %s", url, exc)
        error_msg = f"{type(exc).__name__}: {exc}"
        reachable = False
        model_name = None

    # Check Excel health via com_thread (never raise)
    excel_info: dict[str, str | bool | None]
    try:
        adapter = getattr(request.app.state, "adapter", None)
        if adapter is not None:
            excel_info = await com_thread.run(adapter.describe)
        else:
            excel_info = {
                "connected": False,
                "workbook": None,
                "sheet": None,
                "error": "No adapter configured.",
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Excel health check error: %s", exc)
        excel_info = {
            "connected": False,
            "workbook": None,
            "sheet": None,
            "error": str(exc),
        }

    return HealthResponse(
        backend="ok",
        machine=settings.machine_name,
        llm=LlmHealth(
            reachable=reachable,
            model=model_name,
            error=error_msg,
        ),
        excel=ExcelHealth(
            connected=bool(excel_info.get("connected", False)),
            workbook=excel_info.get("workbook"),  # type: ignore[arg-type]
            sheet=excel_info.get("sheet"),  # type: ignore[arg-type]
            error=excel_info.get("error"),  # type: ignore[arg-type]
        ),
    )
