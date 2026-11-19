"""Pure-ASGI observability middleware.

Per request it: creates the RequestContext (request id / trace id, W3C traceparent aware),
enforces API-version compatibility (APP-R-002), captures the response status, measures latency,
stores a latency sample for the normalised route (APP-R-056) and persists sampled trace spans.
"""
import logging
import random
import re
import time
from datetime import timedelta

from fastapi.responses import JSONResponse

from app import database
from app.config import settings
from app.observability.error_handlers import internal_error_response, log_unhandled
from app.observability.event_logger import log_event
from app.observability.tracing import (
    RequestContext, breakdown_from_spans, new_trace_id, parse_traceparent, set_current,
)
from app.services import performance_service
from app.utils.serialization import new_id, utcnow

logger = logging.getLogger("minishop.middleware")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_VERSION = re.compile(r"^(?:[A-Za-z_-]*?)(\d+)\.(\d+)\.(\d+)$")


def _parse_version(value: str) -> tuple[int, int, int] | None:
    m = _VERSION.match(value.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def evaluate_client_version(header: str | None) -> str:
    """Returns 'unspecified' | 'current' | 'legacy' | 'unsupported'."""
    if not header:
        return "unspecified"
    parsed = _parse_version(header)
    if parsed is None:
        return "unsupported"
    if parsed >= _parse_version(settings.min_client_version):
        return "current"
    if parsed >= _parse_version(settings.legacy_adapter_min_version):
        return "legacy"
    return "unsupported"


class ObservabilityMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        tp = parse_traceparent(headers.get("traceparent"))
        request_id = headers.get("x-request-id", "")
        if not _REQUEST_ID.match(request_id):
            request_id = new_id("req")
        ctx = RequestContext(request_id, tp[0] if tp else new_trace_id(), tp[1] if tp else None)
        ctx.scope = scope
        ctx.method = scope["method"]
        ctx.path = scope["path"]
        ctx.client_version = headers.get("x-client-version")
        ctx.client_id = headers.get("x-client-id")
        set_current(ctx)

        started_at = utcnow()
        t0 = time.perf_counter()
        state = {"status": None, "started": False, "end": None}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["started"] = True
                hdrs = list(message.get("headers", []))
                hdrs.append((b"x-request-id", ctx.request_id.encode()))
                hdrs.append((b"x-trace-id", ctx.trace_id.encode()))
                message = {**message, "headers": hdrs}
            elif message["type"] == "http.response.body" and not message.get("more_body"):
                state["end"] = time.perf_counter()
            await send(message)

        try:
            blocked = None
            if ctx.path.startswith("/api/"):
                blocked = await self._check_version(ctx)
            if blocked is not None:
                await blocked(scope, receive, send_wrapper)
            else:
                await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # noqa: BLE001
            if state["status"] is None:
                state["status"] = 500
            await log_unhandled(exc)
            if not state["started"]:
                await internal_error_response()(scope, receive, send_wrapper)

        try:
            await self._finish(ctx, scope, state, started_at, t0)
        except Exception:  # noqa: BLE001
            logger.exception("observability finalisation failed")

    async def _check_version(self, ctx: RequestContext):
        verdict = evaluate_client_version(ctx.client_version)
        if verdict == "legacy":
            ctx.legacy_client = True
        elif verdict == "unsupported":
            await log_event(
                "API_VERSION_MISMATCH", "WARNING", rule_id="APP-R-002",
                error_code="CLIENT_VERSION_UNSUPPORTED", http_status=426,
                context={"client_version": ctx.client_version, "min_supported": settings.min_client_version,
                         "path": ctx.path},
            )
            return JSONResponse(
                status_code=426,
                content={
                    "success": False,
                    "error": {
                        "code": "CLIENT_VERSION_UNSUPPORTED",
                        "message": "This client version is no longer supported. Please upgrade the application.",
                        "details": {"min_supported_version": settings.min_client_version},
                    },
                    "request_id": ctx.request_id,
                },
                headers={"Upgrade-Required": settings.min_client_version},
            )
        return None

    async def _finish(self, ctx: RequestContext, scope, state, started_at, t0) -> None:
        duration_ms = ((state["end"] or time.perf_counter()) - t0) * 1000
        status = state["status"] or 500
        ctx.http_status = status
        route = scope.get("route")
        template = getattr(route, "path", None)
        endpoint = template or ctx.path
        db = database.get_db()
        if db is None:
            return

        root = {
            "span_id": ctx.root_span_id,
            "parent_span_id": ctx.parent_span_id,
            "operation_name": f"{ctx.method} {endpoint}",
            "operation_type": "request",
            "duration_ms": round(duration_ms, 3),
            "start_time": started_at,
            "end_time": utcnow(),
            "status": "OK" if status < 500 else "ERROR",
            "attributes": {
                "http_method": ctx.method, "http_status": status, "url_path": ctx.path,
                "client_version": ctx.client_version, "db_query_count": ctx.db_query_count,
                "db_duration_ms": round(ctx.db_duration_ms, 3),
            },
        }
        all_spans = ctx.spans + [root]

        if template and performance_service.is_monitored(template):
            timings = breakdown_from_spans(all_spans, ctx.root_span_id, duration_ms)
            try:
                await db.latency_samples.insert_one({
                    "_id": new_id("smp"),
                    "endpoint": template,
                    "http_method": ctx.method,
                    "duration_ms": round(duration_ms, 3),
                    "http_status": status,
                    "timestamp": root["end_time"],
                    "request_id": ctx.request_id,
                    "trace_id": ctx.trace_id,
                    "db_query_count": ctx.db_query_count,
                    "db_duration_ms": round(ctx.db_duration_ms, 3),
                    "operation_timings": timings,
                    "processed": False,
                    "expire_at": root["end_time"] + timedelta(hours=settings.sample_ttl_hours),
                })
            except Exception:  # noqa: BLE001
                logger.exception("failed to store latency sample")

        keep = status >= 500 or duration_ms >= settings.trace_slow_ms
        if keep or random.random() < settings.trace_sample_rate:
            ttl = timedelta(days=settings.trace_keep_ttl_days) if keep else timedelta(hours=settings.trace_ttl_hours)
            docs = [
                {
                    "_id": new_id("spn"),
                    "trace_id": ctx.trace_id,
                    "span_id": s["span_id"],
                    "parent_span_id": s["parent_span_id"],
                    "request_id": ctx.request_id,
                    "endpoint": endpoint,
                    "http_method": ctx.method,
                    "operation_name": s["operation_name"],
                    "operation_type": s["operation_type"],
                    "duration_ms": s["duration_ms"],
                    "start_time": s["start_time"],
                    "end_time": s["end_time"],
                    "status": s["status"],
                    "attributes": s["attributes"],
                    "environment": settings.environment,
                    "expire_at": s["end_time"] + ttl,
                }
                for s in all_spans
            ]
            try:
                await db.trace_spans.insert_many(docs)
            except Exception:  # noqa: BLE001
                logger.exception("failed to store trace spans")
