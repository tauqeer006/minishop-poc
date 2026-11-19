from fastapi import APIRouter, Depends, Query

from app import database
from app.dependencies import require_admin
from app.observability.error_handlers import ok

router = APIRouter(prefix="/api/v1/admin", tags=["observability"])


async def _paged(coll, flt: dict, page: int, page_size: int, sort_field: str = "timestamp") -> dict:
    total = await coll.count_documents(flt)
    items = await coll.find(flt).sort(sort_field, -1).skip((page - 1) * page_size).limit(page_size).to_list(None)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/events")
async def list_events(
    event_type: str | None = None, severity: str | None = None, endpoint: str | None = None,
    rule_id: str | None = None, request_id: str | None = None, error_code: str | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=200),
    admin: dict = Depends(require_admin),
):
    flt = {k: v for k, v in {
        "event_type": event_type, "severity": severity, "endpoint": endpoint,
        "rule_id": rule_id, "request_id": request_id, "error_code": error_code}.items() if v}
    return ok(await _paged(database.get_db().application_events, flt, page, page_size))


@router.get("/audit-logs")
async def list_audit_logs(
    action: str | None = None, entity_type: str | None = None, entity_id: str | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=200),
    admin: dict = Depends(require_admin),
):
    flt = {k: v for k, v in {"action": action, "entity_type": entity_type, "entity_id": entity_id}.items() if v}
    return ok(await _paged(database.get_db().audit_logs, flt, page, page_size))
