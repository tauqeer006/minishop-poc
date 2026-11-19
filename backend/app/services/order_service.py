import hashlib
import json
import uuid

from pymongo.errors import DuplicateKeyError

from app import database, dev_state
from app.observability.error_handlers import AppError
from app.observability.event_logger import audit, log_event, owner_notifier
from app.observability.tracing import span, tdb
from app.utils.serialization import utcnow

ALLOWED_TRANSITIONS = {
    "PENDING": {"CONFIRMED", "CANCELLED"},
    "CONFIRMED": {"SHIPPED", "CANCELLED"},
    "SHIPPED": {"DELIVERED"},
    "DELIVERED": set(),
    "CANCELLED": set(),
}


async def _run_transaction(callback):
    """Run `callback(session)` inside a MongoDB transaction (auto-retries transient errors).
    Requires a replica set (single-node rs0 in docker-compose)."""
    session = database.get_client().start_session()
    try:
        return await session.with_transaction(callback)
    finally:
        await session.end_session()


def fingerprint(user_id: str, items: list[tuple[str, int]]) -> str:
    return hashlib.sha256(json.dumps([user_id, items], sort_keys=True).encode()).hexdigest()


class BusinessRuleViolation(AppError):
    """APP-R-004: raised inside the transaction => everything rolls back."""

    def __init__(self, status: int, code: str, message: str, context: dict) -> None:
        super().__init__(status, code, message, event_type="BUSINESS_INVARIANT_VIOLATION",
                         rule_id="APP-R-004", context=context)


async def create_order(user: dict, raw_items: list[tuple[str, int]], idempotency_key: str) -> tuple[dict, bool]:
    """Returns (order, replayed). Never creates a duplicate for the same (user, idempotency key)."""
    merged: dict[str, int] = {}
    for pid, qty in raw_items:
        merged[pid] = merged.get(pid, 0) + qty
    norm = sorted(merged.items())
    if any(q > 100 for _, q in norm):
        raise AppError(400, "INVALID_DOMAIN_VALUE", "Quantity per product must not exceed 100.",
                       event_type="DOMAIN_VALIDATION_FAILURE", rule_id="APP-R-020")
    fp = fingerprint(user["_id"], norm)

    with span("create_order", "business", item_count=len(norm)):
        existing = await tdb().orders.find_one({"user_id": user["_id"], "idempotency_key": idempotency_key})
        if existing:
            return await _replay(existing, fp), True

        now = utcnow()
        order_id = f"ORD-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"

        async def txn(session):
            products = tdb().products
            items, total = [], 0
            for pid, qty in norm:
                prod = await products.find_one({"_id": pid}, session=session)
                if prod is None:
                    raise BusinessRuleViolation(404, "PRODUCT_NOT_FOUND", "A requested product does not exist.",
                                                {"product_id": pid})
                if not prod["is_active"]:
                    raise BusinessRuleViolation(409, "PRODUCT_UNAVAILABLE", "A requested product is not available.",
                                                {"product_id": pid})
                # Conditional update: succeeds only if enough stock remains (no oversell, no lost update).
                res = await products.update_one(
                    {"_id": pid, "is_active": True, "stock_quantity": {"$gte": qty}},
                    {"$inc": {"stock_quantity": -qty, "version": 1}, "$set": {"updated_at": now}},
                    session=session,
                )
                if res.matched_count != 1:
                    raise BusinessRuleViolation(409, "INSUFFICIENT_STOCK", "Requested quantity is not available.",
                                                {"product_id": pid, "requested": qty,
                                                 "available": prod["stock_quantity"]})
                subtotal = prod["price"] * qty  # price taken from DB, never from the client
                total += subtotal
                items.append({"product_id": pid, "product_name": prod["name"], "quantity": qty,
                              "unit_price": prod["price"], "subtotal": subtotal})
            if dev_state.active() and dev_state.state.checkout_failure:
                raise RuntimeError("Injected checkout failure after inventory update (dev scenario)")
            order = {
                "_id": order_id, "user_id": user["_id"], "items": items, "total_amount": total,
                "status": "PENDING", "idempotency_key": idempotency_key, "request_fingerprint": fp,
                "workflow_id": f"wf-order-processing-{order_id}", "created_at": now, "updated_at": now,
                "status_history": [{"status": "PENDING", "at": now, "by": user["_id"],
                                    "note": "Order placed", "workflow_execution_id": None}],
            }
            await tdb().orders.insert_one(order, session=session)
            return order

        try:
            order = await _run_transaction(txn)
        except BusinessRuleViolation as exc:
            # Transaction already rolled back: record the rejection outside of it.
            await audit("ORDER_REJECTED", "order", None, actor_id=user["_id"], after=exc.context,
                        outcome=f"REJECTED:{exc.code}")
            await owner_notifier.notify("Business invariant violation during checkout",
                                        {"code": exc.code, **exc.context, "user_id": user["_id"]})
            raise
        except DuplicateKeyError:
            existing = await tdb().orders.find_one({"user_id": user["_id"], "idempotency_key": idempotency_key})
            if existing is None:
                raise
            return await _replay(existing, fp), True

    await audit("ORDER_CREATED", "order", order["_id"], actor_id=user["_id"],
                after={"total_amount": order["total_amount"], "items": order["items"]})
    await log_event("ORDER_CREATED", "INFO", http_status=201,
                    context={"order_id": order["_id"], "total_amount": order["total_amount"],
                             "item_count": len(order["items"])})
    return order, False


async def _replay(existing: dict, fp: str) -> dict:
    """APP-R-021: identical retry -> previous order; same key + different payload -> rejected."""
    if existing.get("request_fingerprint") == fp:
        await log_event("DUPLICATE_ORDER_SUBMISSION", "INFO", rule_id="APP-R-021",
                        context={"order_id": existing["_id"], "outcome": "REPLAYED_PREVIOUS_ORDER"})
        return existing
    raise AppError(
        409, "IDEMPOTENCY_KEY_REUSED",
        "This idempotency key was already used with a different request.",
        event_type="DUPLICATE_ORDER_SUBMISSION", rule_id="APP-R-021",
        context={"order_id": existing["_id"], "outcome": "REJECTED_FINGERPRINT_MISMATCH"},
    )


async def list_orders(flt: dict, page: int, page_size: int) -> dict:
    with span("list_orders", "business"):
        total = await tdb().orders.count_documents(flt)
        items = await tdb().orders.find_list(flt, sort=[("created_at", -1)], skip=(page - 1) * page_size,
                                             limit=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def get_order(order_id: str, user: dict) -> dict:
    flt = {"_id": order_id} if user["role"] == "admin" else {"_id": order_id, "user_id": user["_id"]}
    order = await tdb().orders.find_one(flt)
    if not order:
        raise AppError(404, "ORDER_NOT_FOUND", "Order not found.")
    return order


async def update_status(order_id: str, new_status: str, actor: dict, note: str | None,
                        execution_id: str | None) -> tuple[dict, bool]:
    """State machine + workflow dedupe (APP-R-041). Returns (order, duplicate)."""
    now = utcnow()

    async def txn(session):
        orders = tdb().orders
        order = await orders.find_one({"_id": order_id}, session=session)
        if not order:
            raise AppError(404, "ORDER_NOT_FOUND", "Order not found.")
        if execution_id and any(h.get("workflow_execution_id") == execution_id for h in order["status_history"]):
            return order, True  # same workflow execution already applied -> previous result
        if new_status not in ALLOWED_TRANSITIONS[order["status"]]:
            raise BusinessRuleViolation(
                409, "INVALID_STATUS_TRANSITION",
                f"Cannot change order status from {order['status']} to {new_status}.",
                {"order_id": order_id, "from": order["status"], "to": new_status})
        entry = {"status": new_status, "at": now, "by": actor["_id"], "note": note,
                 "workflow_execution_id": execution_id}
        res = await orders.update_one(
            {"_id": order_id, "status": order["status"]},  # conditional: exactly one winner
            {"$set": {"status": new_status, "updated_at": now}, "$push": {"status_history": entry}},
            session=session,
        )
        if res.matched_count != 1:
            raise AppError(409, "ORDER_STATE_CHANGED", "Order status changed concurrently. Reload and retry.")
        if new_status == "CANCELLED":  # side effect applied exactly once (guarded by the update above)
            for item in order["items"]:
                await tdb().products.update_one(
                    {"_id": item["product_id"]},
                    {"$inc": {"stock_quantity": item["quantity"], "version": 1}, "$set": {"updated_at": now}},
                    session=session)
        return await orders.find_one({"_id": order_id}, session=session), False

    with span("update_order_status", "business"):
        try:
            order, duplicate = await _run_transaction(txn)
        except BusinessRuleViolation as exc:
            await audit("ORDER_STATUS_REJECTED", "order", order_id, actor_id=actor["_id"], after=exc.context,
                        outcome=f"REJECTED:{exc.code}")
            raise
    if duplicate:
        await log_event("DUPLICATE_WORKFLOW_EXECUTION", "WARNING", rule_id="APP-R-041",
                        context={"order_id": order_id, "workflow_execution_id": execution_id,
                                 "outcome": "DISCARDED_RETURNED_PREVIOUS_RESULT"})
    else:
        await audit("ORDER_STATUS_CHANGED", "order", order_id, actor_id=actor["_id"],
                    after={"status": new_status, "workflow_execution_id": execution_id})
        await log_event("ORDER_STATUS_CHANGED", "INFO",
                        context={"order_id": order_id, "status": new_status,
                                 "workflow_execution_id": execution_id})
    return order, duplicate
