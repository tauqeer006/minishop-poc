"""DEVELOPMENT-ONLY scenario controls. Router is only mounted when settings.dev_enabled
(ENABLE_DEV_SCENARIOS=true and ENVIRONMENT != production) and every route re-checks it.
These endpoints never disable authentication/validation and never touch business data;
they only switch controlled fault state held in memory (see app/dev_state.py)."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app import database, dev_state
from app.config import settings
from app.dependencies import require_admin
from app.observability.error_handlers import AppError, ok
from app.services import performance_service

router = APIRouter(prefix="/api/v1/dev", tags=["dev-only"])


def _guard() -> None:
    if not settings.dev_enabled:
        raise AppError(404, "NOT_FOUND", "Not found.")


class DevStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_handler: Optional[Literal["optimized", "inefficient"]] = None
    repeat: Optional[int] = Field(default=None, ge=1, le=50)
    query_delay_ms: Optional[float] = Field(default=None, ge=0, le=2000)
    base_delay_ms: Optional[float] = Field(default=None, ge=0, le=2000)
    read_fault_remaining: Optional[int] = Field(default=None, ge=0, le=20)
    checkout_failure: Optional[bool] = None
    monitor_paused: Optional[bool] = None


@router.get("/state")
async def get_state(admin: dict = Depends(require_admin)):
    _guard()
    return ok(dev_state.state.snapshot())


@router.post("/state")
async def set_state(body: DevStateUpdate, admin: dict = Depends(require_admin)):
    _guard()
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(dev_state.state, k, v)
    return ok(dev_state.state.snapshot())


@router.post("/reset")
async def reset(admin: dict = Depends(require_admin)):
    _guard()
    dev_state.state.reset()
    return ok(dev_state.state.snapshot())


@router.post("/monitoring/close-window")
async def close_window(admin: dict = Depends(require_admin)):
    """Close the current monitoring window now (same code path as the periodic monitor)."""
    _guard()
    windows = await performance_service.close_window(database.get_db(), force=True)
    return ok({"windows_closed": len(windows), "windows": [
        {"endpoint": w["endpoint"], "http_method": w["http_method"], "sample_count": w["sample_count"],
         "average_latency_ms": w["average_latency_ms"], "p95_latency_ms": w["p95_latency_ms"],
         "p99_latency_ms": w["p99_latency_ms"], "degradation_status": w["degradation_status"]}
        for w in windows]})
