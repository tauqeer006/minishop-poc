import asyncio
import logging

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient

from app.config import settings

logger = logging.getLogger("minishop.db")

_client: AsyncMongoClient | None = None
_db = None


def init_db(uri: str | None = None, name: str | None = None):
    global _client, _db
    _client = AsyncMongoClient(uri or settings.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    _db = _client[name or settings.db_name]
    return _db


def get_db():
    return _db


def get_client() -> AsyncMongoClient:
    return _client


async def close_db() -> None:
    global _client, _db
    if _client is not None:
        await _client.close()
    _client = None
    _db = None


async def wait_for_primary(timeout_s: int = 90) -> None:
    """Block until MongoDB accepts writes (replica-set primary elected)."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        try:
            hello = await _client.admin.command("hello")
            if hello.get("isWritablePrimary"):
                return
        except Exception as exc:  # noqa: BLE001
            logger.info("waiting for MongoDB primary: %s", type(exc).__name__)
        if asyncio.get_event_loop().time() > deadline:
            raise RuntimeError("MongoDB primary not available (is the replica set initiated?)")
        await asyncio.sleep(2)


async def ensure_indexes(db) -> None:
    """Create all collections' indexes (idempotent)."""
    await db.users.create_index("email", unique=True)

    await db.products.create_index("name")
    await db.products.create_index([("is_active", ASCENDING), ("name", ASCENDING)])

    await db.orders.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.orders.create_index([("user_id", ASCENDING), ("idempotency_key", ASCENDING)], unique=True)
    await db.orders.create_index("workflow_id", unique=True, sparse=True)
    await db.orders.create_index([("status", ASCENDING), ("created_at", DESCENDING)])

    await db.application_events.create_index([("timestamp", DESCENDING)])
    await db.application_events.create_index([("event_type", ASCENDING), ("timestamp", DESCENDING)])
    await db.application_events.create_index("request_id")
    await db.application_events.create_index("trace_id")
    await db.application_events.create_index("rule_id")

    await db.audit_logs.create_index([("timestamp", DESCENDING)])
    await db.audit_logs.create_index([("entity_type", ASCENDING), ("entity_id", ASCENDING)])

    await db.api_latency_metrics.create_index(
        [("endpoint", ASCENDING), ("http_method", ASCENDING), ("window_end", DESCENDING)]
    )
    await db.api_latency_baselines.create_index(
        [("endpoint", ASCENDING), ("http_method", ASCENDING)], unique=True
    )

    await db.trace_spans.create_index("trace_id")
    await db.trace_spans.create_index([("endpoint", ASCENDING), ("end_time", DESCENDING)])
    await db.trace_spans.create_index("expire_at", expireAfterSeconds=0)  # retention (TTL)

    # raw per-request latency samples (input for window aggregation)
    await db.latency_samples.create_index([("processed", ASCENDING), ("timestamp", ASCENDING)])
    await db.latency_samples.create_index("expire_at", expireAfterSeconds=0)

    await db.rectification_incidents.create_index([("endpoint", ASCENDING), ("lifecycle_state", ASCENDING)])
    await db.rectification_incidents.create_index([("detected_at", DESCENDING)])
