from fastapi import APIRouter, Depends, Query

from app.dependencies import require_admin
from app.models.schemas import OrderStatusUpdate
from app.observability.error_handlers import ok
from app.observability.tracing import tdb
from app.services import order_service

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/dashboard")
async def dashboard(admin: dict = Depends(require_admin)):
    db = tdb()
    return ok({
        "total_products": await db.products.count_documents({}),
        "total_customers": await db.users.count_documents({"role": "customer"}),
        "total_orders": await db.orders.count_documents({}),
        "pending_orders": await db.orders.count_documents({"status": "PENDING"}),
    })


@router.get("/orders")
async def all_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, pattern="^(PENDING|CONFIRMED|SHIPPED|DELIVERED|CANCELLED)$"),
    admin: dict = Depends(require_admin),
):
    result = await order_service.list_orders({"status": status} if status else {}, page, page_size)
    ids = list({o["user_id"] for o in result["items"]})
    users = {u["_id"]: u for u in await tdb().users.find_list({"_id": {"$in": ids}})}
    for o in result["items"]:
        u = users.get(o["user_id"], {})
        o["customer_name"], o["customer_email"] = u.get("name"), u.get("email")
    return ok(result)


@router.patch("/orders/{order_id}/status")
async def update_order_status(order_id: str, body: OrderStatusUpdate, admin: dict = Depends(require_admin)):
    order, duplicate = await order_service.update_status(
        order_id, body.status, admin, body.note, body.workflow_execution_id)
    return ok(order, duplicate=duplicate)
