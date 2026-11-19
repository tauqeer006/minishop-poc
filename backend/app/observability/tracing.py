"""Lightweight OpenTelemetry-compatible tracing.

* 32-hex trace ids / 16-hex span ids and W3C `traceparent` propagation, so spans can later be
  exported to an OTel collector unchanged.
* Spans are collected per request on a RequestContext and persisted (sampled) to `trace_spans`
  by the observability middleware.
* TracedCollection wraps MongoDB calls so every database query becomes a `db` span carrying a
  query signature (shape) and fingerprint (shape + values) -> repeated-query evidence.
"""
import asyncio
import contextvars
import hashlib
import json
import random
import re
import secrets
import time
from contextlib import contextmanager

from app.utils.serialization import utcnow

_current: contextvars.ContextVar = contextvars.ContextVar("request_ctx", default=None)
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")

OP_TYPES = ("auth", "authorization", "business", "db", "serialization", "dependency", "data_processing")


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(value: str | None):
    if not value:
        return None
    m = _TRACEPARENT.match(value.strip().lower())
    return (m.group(1), m.group(2)) if m else None


class RequestContext:
    def __init__(self, request_id: str, trace_id: str, parent_span_id: str | None = None) -> None:
        self.request_id = request_id
        self.correlation_id = request_id
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id
        self.root_span_id = new_span_id()
        self.spans: list[dict] = []
        self._stack: list[str] = [self.root_span_id]
        self.scope: dict = {}
        self.method = ""
        self.path = ""
        self.user_id: str | None = None
        self.client_version: str | None = None
        self.client_id: str | None = None
        self.legacy_client = False
        self.http_status: int | None = None
        self.db_query_count = 0
        self.db_duration_ms = 0.0

    @property
    def endpoint(self) -> str:
        route = self.scope.get("route")
        return getattr(route, "path", None) or self.path


def current() -> RequestContext | None:
    return _current.get()


def set_current(ctx: RequestContext | None) -> None:
    _current.set(ctx)


@contextmanager
def span(name: str, op_type: str, **attrs):
    """Record a child span of the current request. No-op outside a request."""
    ctx = current()
    if ctx is None:
        yield {}
        return
    span_id = new_span_id()
    parent = ctx._stack[-1]
    ctx._stack.append(span_id)
    rec = {
        "span_id": span_id,
        "parent_span_id": parent,
        "operation_name": name,
        "operation_type": op_type,
        "start_time": utcnow(),
        "status": "OK",
        "attributes": dict(attrs),
    }
    t0 = time.perf_counter()
    try:
        yield rec["attributes"]
    except BaseException as exc:
        rec["status"] = "ERROR"
        rec["attributes"]["exception_type"] = type(exc).__name__
        raise
    finally:
        rec["duration_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        rec["end_time"] = utcnow()
        if ctx._stack and ctx._stack[-1] == span_id:
            ctx._stack.pop()
        ctx.spans.append(rec)


def breakdown_from_spans(spans: list[dict], root_span_id: str, total_ms: float) -> dict:
    """Exclusive (self) time per operation type. Nested spans are not double counted:
    each span's self time = its duration minus the durations of its direct children.
    Root self time (and anything not covered by a child span) is reported as `other`."""
    child_sum: dict[str, float] = {}
    for s in spans:
        parent = s.get("parent_span_id")
        if parent:
            child_sum[parent] = child_sum.get(parent, 0.0) + s["duration_ms"]
    out: dict[str, float] = {}
    for s in spans:
        if s["span_id"] == root_span_id or s.get("operation_type") == "request":
            continue
        self_ms = max(s["duration_ms"] - child_sum.get(s["span_id"], 0.0), 0.0)
        out[s["operation_type"]] = out.get(s["operation_type"], 0.0) + self_ms
    covered = sum(out.values())
    out["other"] = max(total_ms - covered, 0.0)
    return {k: round(v, 3) for k, v in out.items()}


def _filter_keys(filt) -> list[str]:
    if isinstance(filt, dict):
        return sorted(str(k) for k in filt.keys())
    if isinstance(filt, list):
        return ["pipeline"]
    return []


class TracedCollection:
    """Thin async wrapper adding a `db` span (and request-level query counters) per operation."""

    def __init__(self, coll) -> None:
        self._c = coll

    async def _run(self, op: str, filt, fn, simulate_delay_ms: float = 0.0):
        ctx = current()
        name = self._c.name
        signature = f"{name}.{op}({','.join(_filter_keys(filt))})"
        fingerprint = hashlib.sha1(json.dumps(filt, sort_keys=True, default=str).encode()).hexdigest()[:12]
        t0 = time.perf_counter()
        try:
            with span(
                f"db.{name}.{op}", "db",
                collection=name, db_operation=op, query_signature=signature, query_fingerprint=fingerprint,
            ):
                result = await fn()
                if simulate_delay_ms > 0:  # dev-only simulated round-trip latency (see dev_state)
                    await asyncio.sleep(simulate_delay_ms * random.uniform(0.9, 1.15) / 1000)
                return result
        finally:
            if ctx is not None:
                ctx.db_query_count += 1
                ctx.db_duration_ms += (time.perf_counter() - t0) * 1000

    async def find_one(self, filt, simulate_delay_ms: float = 0.0, **kw):
        return await self._run("find_one", filt, lambda: self._c.find_one(filt, **kw), simulate_delay_ms)

    async def find_list(self, filt=None, sort=None, skip=0, limit=0, projection=None, **kw):
        filt = filt or {}

        async def fn():
            cur = self._c.find(filt, projection, **kw)
            if sort:
                cur = cur.sort(sort)
            if skip:
                cur = cur.skip(skip)
            if limit:
                cur = cur.limit(limit)
            return await cur.to_list(None)

        return await self._run("find", filt, fn)

    async def aggregate_list(self, pipeline, **kw):
        async def fn():
            cur = await self._c.aggregate(pipeline, **kw)
            return await cur.to_list(None)

        return await self._run("aggregate", pipeline, fn)

    async def count_documents(self, filt, **kw):
        return await self._run("count_documents", filt, lambda: self._c.count_documents(filt, **kw))

    async def insert_one(self, doc, **kw):
        return await self._run("insert_one", {"_id": doc.get("_id")}, lambda: self._c.insert_one(doc, **kw))

    async def update_one(self, filt, update, **kw):
        return await self._run("update_one", filt, lambda: self._c.update_one(filt, update, **kw))

    async def find_one_and_update(self, filt, update, **kw):
        return await self._run("find_one_and_update", filt, lambda: self._c.find_one_and_update(filt, update, **kw))


class TracedDB:
    def __init__(self, db) -> None:
        self._db = db

    def __getitem__(self, name: str) -> TracedCollection:
        return TracedCollection(self._db[name])

    def __getattr__(self, name: str) -> TracedCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return TracedCollection(self._db[name])


def tdb() -> TracedDB:
    from app import database
    return TracedDB(database.get_db())
