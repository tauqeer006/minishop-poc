"""APP-R-056 read APIs. Administrator-only. Values come straight from measured collections."""
from fastapi import APIRouter, Depends, Query

from app import database
from app.dependencies import require_admin
from app.observability.error_handlers import AppError, ok
from app.services import performance_service

router = APIRouter(prefix="/api/v1/admin/performance", tags=["performance"])


@router.get("/endpoints")
async def endpoints(admin: dict = Depends(require_admin)):
    db = database.get_db()
    cur = await db.api_latency_metrics.aggregate([
        {"$sort": {"window_end": -1}},
        {"$group": {"_id": {"e": "$endpoint", "m": "$http_method"}, "w": {"$first": "$$ROOT"}}},
    ])
    latest = await cur.to_list(None)
    baselines = {(b["endpoint"], b["http_method"]): b for b in await db.api_latency_baselines.find({}).to_list(None)}
    open_incidents = {
        (i["endpoint"], i["http_method"]): i["_id"]
        for i in await db.rectification_incidents.find(
            {"incident_type": "API_RESPONSE_TIME_DEGRADATION", "closed_at": None}).to_list(None)
    }
    items = []
    for row in latest:
        w, key = row["w"], (row["_id"]["e"], row["_id"]["m"])
        b = baselines.get(key)
        status = w["degradation_status"]
        if key in open_incidents:
            status = "DEGRADED"
        items.append({
            "endpoint": key[0], "http_method": key[1], "status": status, "window_end": w["window_end"],
            "sample_count": w["sample_count"], "average_latency_ms": w["average_latency_ms"],
            "p95_latency_ms": w["p95_latency_ms"], "p99_latency_ms": w["p99_latency_ms"],
            "baseline_average_ms": b["baseline_average_ms"] if b else None,
            "baseline_p95_ms": b["baseline_p95_ms"] if b else None,
            "baseline_p99_ms": b["baseline_p99_ms"] if b else None,
            "baseline_status": b["status"] if b else None,
            "open_incident_id": open_incidents.get(key),
        })
    items.sort(key=lambda r: (r["endpoint"], r["http_method"]))
    summary = {
        "monitored": len(items),
        "normal": sum(1 for r in items if r["status"] in ("NORMAL", "LEARNING", "INSUFFICIENT_DATA", "SUSPECT")),
        "degraded": sum(1 for r in items if r["status"] == "DEGRADED"),
        "active_incidents": len(open_incidents),
    }
    return ok({"summary": summary, "items": items})


@router.get("/metrics")
async def metrics(endpoint: str | None = None, method: str | None = None,
                  limit: int = Query(default=60, ge=1, le=500), admin: dict = Depends(require_admin)):
    flt = {k: v for k, v in {"endpoint": endpoint, "http_method": method.upper() if method else None}.items() if v}
    rows = await database.get_db().api_latency_metrics.find(flt).sort("window_end", -1).limit(limit).to_list(None)
    return ok({"items": list(reversed(rows))})


@router.get("/baselines")
async def baselines(admin: dict = Depends(require_admin)):
    rows = await database.get_db().api_latency_baselines.find({}).sort("endpoint", 1).to_list(None)
    return ok({"items": rows})


@router.get("/incidents")
async def incidents(lifecycle: str | None = None, endpoint: str | None = None,
                    limit: int = Query(default=50, ge=1, le=200), admin: dict = Depends(require_admin)):
    flt = {k: v for k, v in {"lifecycle_state": lifecycle, "endpoint": endpoint}.items() if v}
    rows = await database.get_db().rectification_incidents.find(flt).sort("detected_at", -1).limit(limit).to_list(None)
    return ok({"items": rows})


@router.get("/traces/{trace_id}")
async def trace(trace_id: str, admin: dict = Depends(require_admin)):
    data = await performance_service.get_trace(database.get_db(), trace_id)
    if not data:
        raise AppError(404, "TRACE_NOT_FOUND", "Trace not found (it may have expired or was not sampled).")
    return ok(data)
