"""Centralised structured events: JSON on stdout + `application_events` collection."""
import json
import logging

from app import database
from app.config import settings
from app.observability.tracing import current
from app.utils.serialization import new_id, sanitize, utcnow

logger = logging.getLogger("minishop.events")


async def log_event(
    event_type: str,
    severity: str = "INFO",
    *,
    rule_id: str | None = None,
    error_code: str | None = None,
    exception_type: str | None = None,
    http_status: int | None = None,
    endpoint: str | None = None,
    duration_ms: float | None = None,
    user_id: str | None = None,
    context: dict | None = None,
    **extra,
) -> None:
    """Never raises: observability must not break the request path."""
    ctx = current()
    doc = {
        "_id": new_id("evt"),
        "timestamp": utcnow(),
        "event_type": event_type,
        "severity": severity,
        "request_id": ctx.request_id if ctx else None,
        "correlation_id": ctx.correlation_id if ctx else None,
        "trace_id": ctx.trace_id if ctx else None,
        "endpoint": endpoint or (ctx.endpoint if ctx else None),
        "http_method": ctx.method if ctx else None,
        "http_status": http_status if http_status is not None else (ctx.http_status if ctx else None),
        "duration_ms": duration_ms,
        "user_id": user_id or (ctx.user_id if ctx else None),
        "client_id": ctx.client_id if ctx else None,
        "api_version": ctx.client_version if ctx else None,
        "error_code": error_code,
        "exception_type": exception_type,
        "context": sanitize(context or {}),
        "source": "backend",
        "environment": settings.environment,
        "rule_id": rule_id,
    }
    doc.update(sanitize(extra))
    try:
        logger.info(json.dumps(doc, default=str))
        db = database.get_db()
        if db is not None:
            await db.application_events.insert_one(doc)
    except Exception:  # noqa: BLE001
        logger.exception("failed to persist application event %s", event_type)


async def audit(
    action: str,
    entity_type: str,
    entity_id: str | None,
    *,
    actor_id: str | None = None,
    before=None,
    after=None,
    outcome: str = "SUCCESS",
) -> None:
    ctx = current()
    doc = {
        "_id": new_id("aud"),
        "timestamp": utcnow(),
        "actor_id": actor_id or (ctx.user_id if ctx else None),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before": sanitize(before),
        "after": sanitize(after),
        "request_id": ctx.request_id if ctx else None,
        "outcome": outcome,
    }
    try:
        await database.get_db().audit_logs.insert_one(doc)
    except Exception:  # noqa: BLE001
        logger.exception("failed to persist audit log %s", action)


class OwnerNotifier:
    """APP-R-004 owner-notification interface. No delivery channel is configured in this POC
    (no e-mail integration by design); notifications are only logged."""

    async def notify(self, subject: str, details: dict) -> None:
        logger.warning(json.dumps({"owner_notification": subject, "details": sanitize(details),
                                   "delivery": "NOT_CONFIGURED"}, default=str))


owner_notifier = OwnerNotifier()
