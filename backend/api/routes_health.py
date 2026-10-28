import logging

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class LlmHealth(BaseModel):
    """Health status of the local LLM server."""

    reachable: bool
    model: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    """Health check response schema."""

    backend: str
    machine: str
    llm: LlmHealth


@router.get("/health", response_model=HealthResponse)
async def check_health() -> HealthResponse:
    """Check health of backend and local LLM server."""
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
            if isinstance(data, dict) and "data" in data and len(data["data"]) > 0:
                first_model = data["data"][0]
                model_name = (
                    first_model.get("id") if isinstance(first_model, dict) else str(first_model)
                )
            elif isinstance(data, list) and len(data) > 0:
                first_model = data[0]
                model_name = (
                    first_model.get("id") if isinstance(first_model, dict) else str(first_model)
                )
            else:
                model_name = settings.llm_model
            reachable = True
    except Exception as exc:  # noqa: BLE001 (spec requires never raising; catch-all for any error)
        logger.warning("LLM server unreachable at %s: %s", url, exc)
        error_msg = f"{type(exc).__name__}: {exc}"
        reachable = False
        model_name = None

    return HealthResponse(
        backend="ok",
        machine=settings.machine_name,
        llm=LlmHealth(
            reachable=reachable,
            model=model_name,
            error=error_msg,
        ),
    )
