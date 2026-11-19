import re

from fastapi import APIRouter, Depends, Header, Query, Response

from app.dependencies import get_current_user
from app.models.schemas import OrderCreate
from app.observability.error_handlers import AppError, ok
from app.observability.event_logger import log_event
from app.observability.tracing import current
from app.services import order_service
from app.utils.retry import retry_idempotent

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])
_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")


@router.post("")
async def create_order(
    body: OrderCreate,
    user: dict = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise AppError(400, "IDEMPOTENCY_KEY_REQUIRED", "The Idempotency-Key header is required for checkout.",
                       event_type="REQUEST_VALIDATION_FAILURE", rule_id="APP-R-021")
    if not _KEY.match(idempotency_key):
        raise AppError(400, "IDEMPOTENCY_KEY_INVALID",
                       "Idempotency-Key must be 8-64 characters (letters, digits, . _ : -).",
                       event_type="REQUEST_VALIDATION_FAILURE", rule_id="APP-R-021")

    headers = {}
    ctx = current()
    if body.cart is not None:
        # APP-R-002 adapter: only the explicitly supported legacy contract (0.9.x) is adapted.
        if not (ctx and ctx.legacy_client):
            raise AppError(400, "REQUEST_SCHEMA_INVALID", "`cart` is only accepted from legacy clients.",
                           event_type="REQUEST_VALIDATION_FAILURE", rule_id="APP-R-002")
        items = [(c.id, c.qty) for c in body.cart]
        headers = {"Deprecation": "true", "X-Client-Version-Adapter": "legacy-0.9-cart"}
        await log_event("API_VERSION_ADAPTER_APPLIED", "INFO", rule_id="APP-R-002",
                        context={"adapter": "legacy-0.9-cart", "client_version": ctx.client_version})
    else:
        items = [(i.product_id, i.quantity) for i in body.items]
        if ctx and ctx.legacy_client:
            headers = {"Deprecation": "true"}

    order, replayed = await order_service.create_order(user, items, idempotency_key)
    if replayed:
        headers["Idempotent-Replay"] = "true"
    return ok(order, status_code=200 if replayed else 201, headers=headers or None)


@router.get("")
async def my_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, pattern="^(PENDING|CONFIRMED|SHIPPED|DELIVERED|CANCELLED)$"),
    user: dict = Depends(get_current_user),
):
    flt = {"user_id": user["_id"]}
    if status:
        flt["status"] = status
    return ok(await order_service.list_orders(flt, page, page_size))


@router.get("/{order_id}")
async def order_detail(order_id: str, user: dict = Depends(get_current_user)):
    order = await retry_idempotent(lambda: order_service.get_order(order_id, user), operation="get_order")
    return ok(order)
