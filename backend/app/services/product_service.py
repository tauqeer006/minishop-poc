import asyncio
import re

from app import dev_state
from app.config import settings
from app.observability.error_handlers import AppError
from app.observability.event_logger import audit, log_event
from app.observability.tracing import span, tdb
from app.utils.retry import TransientDependencyError, backoff_delay
from app.utils.serialization import new_id, utcnow


def _maybe_inject_read_fault() -> None:
    if dev_state.consume_read_fault():  # dev-only (APP-R-030 scenario)
        raise TransientDependencyError("Injected transient read failure (dev scenario)")


async def list_products(search: str | None, page: int, page_size: int, include_inactive: bool) -> dict:
    """Idempotent read -> callers wrap it in retry_idempotent (APP-R-030)."""
    with span("list_products", "business"):
        _maybe_inject_read_fault()
        flt: dict = {} if include_inactive else {"is_active": True}
        if search:
            rx = {"$regex": re.escape(search.strip()), "$options": "i"}
            flt["$or"] = [{"name": rx}, {"description": rx}]
        total = await tdb().products.count_documents(flt)
        items = await tdb().products.find_list(flt, sort=[("name", 1)], skip=(page - 1) * page_size, limit=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def _lookup_optimized(product_id: str, delay_ms: float):
    """Approved data-access path: ONE query."""
    return await tdb().products.find_one({"_id": product_id}, simulate_delay_ms=delay_ms)


async def _lookup_inefficient(product_id: str, delay_ms: float, repeat: int):
    """DEVELOPMENT-ONLY deliberately inefficient handler: the same product query is executed
    `repeat` times (redundant repeated DB queries). Result is identical to the optimized path."""
    doc = None
    for _ in range(max(repeat, 1)):
        doc = await tdb().products.find_one({"_id": product_id}, simulate_delay_ms=delay_ms)
    return doc


async def get_product(product_id: str, include_inactive: bool = False) -> dict:
    """Product-details lookup (APP-R-056 target endpoint). Idempotent read."""
    dev = dev_state.active()
    mode = dev_state.state.product_handler if dev else "optimized"
    delay = dev_state.state.query_delay_ms if dev else 0.0
    with span("product_details_lookup", "business", handler=mode):
        _maybe_inject_read_fault()
        if dev and dev_state.state.base_delay_ms > 0:  # simulated non-DB business processing
            await asyncio.sleep(dev_state.state.base_delay_ms / 1000)
        if mode == "inefficient":
            doc = await _lookup_inefficient(product_id, delay, dev_state.state.repeat)
        else:
            doc = await _lookup_optimized(product_id, delay)
    if not doc or (not doc["is_active"] and not include_inactive):
        raise AppError(404, "PRODUCT_NOT_FOUND", "Product not found.")
    return doc


async def create_product(data: dict, actor_id: str) -> dict:
    now = utcnow()
    doc = {"_id": new_id("prd"), **data, "version": 1, "created_at": now, "updated_at": now}
    with span("create_product", "business"):
        await tdb().products.insert_one(doc)
    await audit("PRODUCT_CREATED", "product", doc["_id"], actor_id=actor_id, after=doc)
    return doc


async def update_product(product_id: str, changes: dict, expected_version: int | None,
                         stock_delta: int | None, actor_id: str) -> dict:
    """APP-R-040: conditional update on `version`. Never overwrites newer data with stale data.
    * expected_version given  -> strict: mismatch => 409 (client must reload).
    * not given               -> bounded read-modify-conditional-write retries with jitter."""
    attempts = 1 if expected_version is not None else settings.optimistic_retry_attempts
    products = tdb().products
    with span("update_product", "business"):
        for attempt in range(1, attempts + 1):
            current = await products.find_one({"_id": product_id})
            if not current:
                raise AppError(404, "PRODUCT_NOT_FOUND", "Product not found.")
            if expected_version is not None and current["version"] != expected_version:
                await _conflict(product_id, expected_version, current["version"], attempt, "stale_expected_version")
                raise AppError(409, "VERSION_CONFLICT",
                               "The product was modified by someone else. Reload and retry.",
                               details={"current_version": current["version"]})
            flt = {"_id": product_id, "version": current["version"]}
            update: dict = {"$set": {**changes, "updated_at": utcnow()}, "$inc": {"version": 1}}
            if stock_delta:
                update["$inc"]["stock_quantity"] = stock_delta
                if stock_delta < 0:
                    flt["stock_quantity"] = {"$gte": -stock_delta}
            res = await products.update_one(flt, update)
            if res.matched_count == 1:
                new = await products.find_one({"_id": product_id})
                await audit("PRODUCT_UPDATED", "product", product_id, actor_id=actor_id,
                            before={k: current[k] for k in ("name", "price", "stock_quantity", "is_active", "version")},
                            after={k: new[k] for k in ("name", "price", "stock_quantity", "is_active", "version")})
                return new
            latest = await products.find_one({"_id": product_id})
            if latest and latest["version"] == current["version"] and stock_delta and stock_delta < 0:
                raise AppError(400, "INVALID_DOMAIN_VALUE", "Stock cannot become negative.")
            await _conflict(product_id, current["version"], latest["version"] if latest else None, attempt,
                            "concurrent_update")
            if attempt < attempts:
                await asyncio.sleep(backoff_delay(attempt))
    raise AppError(409, "VERSION_CONFLICT", "Concurrent updates prevented this change. Retry.",
                   details={"attempts": attempts})


async def _conflict(product_id: str, expected, actual, attempt: int, reason: str) -> None:
    await log_event(
        "OPTIMISTIC_LOCK_CONFLICT", "WARNING", rule_id="APP-R-040", error_code="VERSION_CONFLICT",
        context={"product_id": product_id, "expected_version": expected, "actual_version": actual,
                 "attempt": attempt, "reason": reason},
    )
