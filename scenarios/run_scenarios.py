#!/usr/bin/env python3
"""Development-only scenario runner for the nine selected rectification rules.

* Uses ONLY the real HTTP API (plus the admin-protected /api/v1/dev/* fault controls, which exist
  only when the backend runs with ENABLE_DEV_SCENARIOS=true and ENVIRONMENT != production).
* Disabled by default: pass --enable (or set ENABLE_SCENARIO_RUNNER=true).
* Standard library only (Python 3.9+), no installation needed.

Examples:
    python scenarios/run_scenarios.py --enable
    python scenarios/run_scenarios.py --enable --only APP-R-021,APP-R-056
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

BASE = "http://localhost:8000"
RESULTS: list[tuple[str, bool, str]] = []


# ------------------------------------------------------------------ http helpers
def call(method, path, body=None, token=None, headers=None, raw=None, timeout=120):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json", "X-Client-Version": "1.0.0"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, hdrs, text = r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        status, hdrs, text = e.code, e.headers, e.read()
    try:
        js = json.loads(text)
    except ValueError:
        js = None
    return status, hdrs, js


def check(rule, name, cond, detail=""):
    RESULTS.append((rule, bool(cond), f"{name} {detail}".strip()))
    print(f"    [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    return cond


def show(rule, title, doc):
    print(f"\n=== {rule} — {title} ===")
    for k, v in doc.items():
        print(f"  {k:<24}: {v}")


def events(token, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    _, _, js = call("GET", f"/api/v1/admin/events?{q}&page_size=100", token=token)
    return js["data"]["items"] if js and js.get("success") else []


# ------------------------------------------------------------------ setup
class Ctx:
    admin = customer = product_id = None


def setup(args):
    s, _, js = call("GET", "/api/v1/dev/state")  # unauthenticated: 401 if dev routes exist, 404 if not
    if s == 404:
        sys.exit("Dev scenario endpoints are not available (ENABLE_DEV_SCENARIOS must be true and "
                 "ENVIRONMENT must not be production). Refusing to run.")
    s, _, js = call("POST", "/api/v1/auth/login", {"email": args.admin_email, "password": args.admin_password})
    if s != 200:
        sys.exit(f"Admin login failed ({s}). Check --admin-email/--admin-password.")
    Ctx.admin = js["data"]["access_token"]
    email = f"scn-{uuid.uuid4().hex[:8]}@minishop.dev"
    s, _, js = call("POST", "/api/v1/auth/register", {"name": "Scenario Customer", "email": email,
                                                       "password": "Scenario@123"})
    Ctx.customer = js["data"]["access_token"]
    s, _, js = call("POST", "/api/v1/products", {"name": f"Scenario Product {uuid.uuid4().hex[:6]}",
                                                  "description": "scenario runner product", "price": 1999,
                                                  "stock_quantity": 20}, token=Ctx.admin)
    Ctx.product_id = js["data"]["id"]
    call("POST", "/api/v1/dev/reset", token=Ctx.admin)
    print(f"setup ok: scenario product {Ctx.product_id}")


def stock():
    return call("GET", f"/api/v1/products/{Ctx.product_id}")[2]["data"]["stock_quantity"]


def order(items, key, token=None, headers=None, body=None, raw=None):
    return call("POST", "/api/v1/orders", body if body is not None else {"items": items}, token=token or Ctx.customer,
                headers={"Idempotency-Key": key, **(headers or {})}, raw=raw)


def order_count():
    return call("GET", "/api/v1/orders?page_size=100", token=Ctx.customer)[2]["data"]["total"]


# ------------------------------------------------------------------ scenarios
def s001():
    show("APP-R-001", "Reject malformed requests before business logic", {
        "initial condition": "customer authenticated, valid product",
        "trigger": "POST /orders with truncated JSON body",
        "detection signal": "HTTP 400, MALFORMED_JSON",
        "expected behaviour": "rejected before business logic; stable error code",
        "expected event": "REQUEST_VALIDATION_FAILURE (rule APP-R-001)",
        "expected DB state": "no order created, stock unchanged",
        "future ML": "malformed vs. legitimate-unusual input", "future action": "reject (already enforced)",
        "verification": "order count and stock identical before/after"})
    before_o, before_s = order_count(), stock()
    s, h, js = order(None, "scn-001-" + uuid.uuid4().hex[:8], raw=b'{"items": [ {"product_id": "x", "quantity": ')
    check("APP-R-001", "HTTP 400 + MALFORMED_JSON", s == 400 and js["error"]["code"] == "MALFORMED_JSON", f"(got {s})")
    check("APP-R-001", "no order / stock change", order_count() == before_o and stock() == before_s)
    ev = events(Ctx.admin, rule_id="APP-R-001", request_id=h["X-Request-ID"])
    check("APP-R-001", "structured event recorded", any(e["event_type"] == "REQUEST_VALIDATION_FAILURE" for e in ev))


def s002():
    show("APP-R-002", "Enforce API version compatibility", {
        "initial condition": "backend min supported client 1.0.0; legacy adapter for 0.9.x",
        "trigger": "requests with X-Client-Version 0.5.0 (unsupported) and 0.9.0 (legacy cart contract)",
        "detection signal": "API contract mismatch / unsupported client version",
        "expected behaviour": "0.5.0 -> 426 upgrade required; 0.9.0 -> adapter; 1.0.0 -> normal",
        "expected event": "API_VERSION_MISMATCH / API_VERSION_ADAPTER_APPLIED",
        "expected DB state": "no change for the rejected request", "future ML": "version-specific regressions",
        "future action": "adapter / upgrade-required (already enforced)",
        "verification": "supported clients keep working; unsupported get stable error"})
    s, h, js = call("GET", "/api/v1/products", headers={"X-Client-Version": "0.5.0"})
    check("APP-R-002", "unsupported version -> 426", s == 426 and js["error"]["code"] == "CLIENT_VERSION_UNSUPPORTED")
    check("APP-R-002", "supported version still works",
          call("GET", "/api/v1/products", headers={"X-Client-Version": "1.0.0"})[0] == 200)
    s, h, js = order(None, "scn-002-" + uuid.uuid4().hex[:8], body={"cart": [{"id": Ctx.product_id, "qty": 1}]},
                     headers={"X-Client-Version": "0.9.0"})
    check("APP-R-002", "legacy client adapted", s == 201 and h.get("X-Client-Version-Adapter") == "legacy-0.9-cart")
    ev = events(Ctx.admin, rule_id="APP-R-002")
    check("APP-R-002", "events recorded", {"API_VERSION_MISMATCH", "API_VERSION_ADAPTER_APPLIED"} <=
          {e["event_type"] for e in ev})


def s004():
    show("APP-R-004", "Prevent business-rule bypass", {
        "initial condition": f"product stock = {stock()}",
        "trigger": "order quantity exceeding available stock",
        "detection signal": "business invariant violation / rejected transaction",
        "expected behaviour": "HTTP 409 INSUFFICIENT_STOCK, transaction rolled back",
        "expected event": "BUSINESS_INVARIANT_VIOLATION + audit log ORDER_REJECTED",
        "expected DB state": "no order, stock unchanged", "future ML": "unusual violation combinations",
        "future action": "reject + audit + owner notification (interface only)",
        "verification": "no invariant-violating record persisted"})
    before_o, before_s = order_count(), stock()
    s, _, js = order([{"product_id": Ctx.product_id, "quantity": 100}], "scn-004-" + uuid.uuid4().hex[:8])
    check("APP-R-004", "409 INSUFFICIENT_STOCK", s == 409 and js["error"]["code"] == "INSUFFICIENT_STOCK", f"(got {s})")
    check("APP-R-004", "nothing persisted", order_count() == before_o and stock() == before_s)
    _, _, a = call("GET", "/api/v1/admin/audit-logs?action=ORDER_REJECTED&page_size=5", token=Ctx.admin)
    check("APP-R-004", "audit log ORDER_REJECTED", a["data"]["total"] >= 1)


def s020():
    show("APP-R-020", "Reject invalid domain data", {
        "initial condition": "authenticated customer/admin",
        "trigger": "negative order quantity; negative product price",
        "detection signal": "validation failure on domain values",
        "expected behaviour": "HTTP 400 INVALID_DOMAIN_VALUE at the boundary",
        "expected event": "DOMAIN_VALIDATION_FAILURE (rule APP-R-020; submitted values not stored)",
        "expected DB state": "no order / product created", "future ML": "novel invalid-value patterns",
        "future action": "reject, require corrected input (already enforced)",
        "verification": "invalid data never enters business collections"})
    before = order_count()
    s, _, js = order([{"product_id": Ctx.product_id, "quantity": -3}], "scn-020-" + uuid.uuid4().hex[:8])
    check("APP-R-020", "negative quantity -> 400", s == 400 and js["error"]["code"] == "INVALID_DOMAIN_VALUE")
    s, _, js = call("POST", "/api/v1/products", {"name": "Bad Price", "price": -5, "stock_quantity": 1},
                    token=Ctx.admin)
    check("APP-R-020", "negative price -> 400", s == 400 and js["error"]["code"] == "INVALID_DOMAIN_VALUE")
    check("APP-R-020", "no order created", order_count() == before)


def s021():
    show("APP-R-021", "Prevent duplicate entity creation", {
        "initial condition": f"stock = {stock()}",
        "trigger": "same checkout (same Idempotency-Key) submitted 3 times + once with a different payload",
        "detection signal": "duplicate idempotency key / repeated submission",
        "expected behaviour": "1st 201, retries 200 returning the same order; changed payload -> 409",
        "expected event": "DUPLICATE_ORDER_SUBMISSION (rule APP-R-021)",
        "expected DB state": "exactly one order; stock decremented once", "future ML": "duplicate submission patterns",
        "future action": "idempotent replay (already enforced)", "verification": "one order for one valid key"})
    key, items = "scn-021-" + uuid.uuid4().hex[:8], [{"product_id": Ctx.product_id, "quantity": 1}]
    s0, before = stock(), order_count()
    rs = [order(items, key) for _ in range(3)]
    ids = {r[2]["data"]["id"] for r in rs}
    check("APP-R-021", "statuses 201,200,200", [r[0] for r in rs] == [201, 200, 200], f"(got {[r[0] for r in rs]})")
    check("APP-R-021", "same order id returned", len(ids) == 1)
    check("APP-R-021", "one order, stock -1", order_count() == before + 1 and stock() == s0 - 1)
    s, _, js = order([{"product_id": Ctx.product_id, "quantity": 2}], key)
    check("APP-R-021", "key reuse with other payload -> 409", s == 409 and js["error"]["code"] == "IDEMPOTENCY_KEY_REUSED")


def s030():
    show("APP-R-030", "Apply bounded retry with jitter", {
        "initial condition": "dev fault state: N transient failures injected into product reads",
        "trigger": "GET /products/{id} (idempotent read) with 2 injected failures, then with 10",
        "detection signal": "transient dependency failure",
        "expected behaviour": "2 failures -> recovered (retries w/ exponential backoff + jitter); 10 -> 503 after budget",
        "expected event": "TRANSIENT_DEPENDENCY_FAILURE x attempts, TRANSIENT_DEPENDENCY_RECOVERED",
        "expected DB state": "no business effect (read only; checkout is never retried)",
        "future ML": "transient vs persistent failures", "future action": "bounded retry (already enforced)",
        "verification": "recovered read, bounded attempts, no duplicate effects"})
    n0 = len(events(Ctx.admin, event_type="TRANSIENT_DEPENDENCY_FAILURE"))
    call("POST", "/api/v1/dev/state", {"read_fault_remaining": 2}, token=Ctx.admin)
    s, _, _ = call("GET", f"/api/v1/products/{Ctx.product_id}")
    check("APP-R-030", "recovered after 2 transient failures", s == 200, f"(got {s})")
    n1 = len(events(Ctx.admin, event_type="TRANSIENT_DEPENDENCY_FAILURE"))
    check("APP-R-030", "2 failure events recorded", n1 - n0 == 2, f"(delta {n1 - n0})")
    call("POST", "/api/v1/dev/state", {"read_fault_remaining": 10}, token=Ctx.admin)
    s, _, js = call("GET", f"/api/v1/products/{Ctx.product_id}")
    check("APP-R-030", "budget exhausted -> 503", s == 503 and js["error"]["code"] == "DEPENDENCY_UNAVAILABLE")
    call("POST", "/api/v1/dev/state", {"read_fault_remaining": 0}, token=Ctx.admin)


def s040():
    show("APP-R-040", "Resolve optimistic-lock conflicts", {
        "initial condition": "product at version V",
        "trigger": "two admins PATCH stock concurrently with the same expected_version",
        "detection signal": "version-conflict", "expected behaviour": "one 200, one 409 VERSION_CONFLICT",
        "expected event": "OPTIMISTIC_LOCK_CONFLICT (rule APP-R-040)",
        "expected DB state": "stock changed once; version incremented once (no lost update)",
        "future ML": "contention hotspots", "future action": "conditional update / bounded retry (enforced)",
        "verification": "no stale overwrite"})
    p = call("GET", f"/api/v1/products/{Ctx.product_id}")[2]["data"]
    body = {"stock_delta": -1, "expected_version": p["version"]}
    with ThreadPoolExecutor(2) as ex:
        rs = list(ex.map(lambda _: call("PATCH", f"/api/v1/products/{Ctx.product_id}", body, token=Ctx.admin), range(2)))
    codes = sorted(r[0] for r in rs)
    check("APP-R-040", "exactly one winner", codes == [200, 409], f"(got {codes})")
    q = call("GET", f"/api/v1/products/{Ctx.product_id}")[2]["data"]
    check("APP-R-040", "single stock change / version bump", q["stock_quantity"] == p["stock_quantity"] - 1
          and q["version"] == p["version"] + 1)


def s041():
    show("APP-R-041", "Prevent duplicate workflow execution", {
        "initial condition": "PENDING order",
        "trigger": "same workflow_execution_id (CANCELLED) sent twice",
        "detection signal": "duplicate workflow id / repeated processing event",
        "expected behaviour": "second call returns previous result with duplicate=true",
        "expected event": "DUPLICATE_WORKFLOW_EXECUTION (rule APP-R-041)",
        "expected DB state": "one status-history entry; stock restored exactly once",
        "future ML": "duplicate workflow patterns", "future action": "unique execution id + state machine (enforced)",
        "verification": "exactly one intended business effect"})
    s0 = stock()
    _, _, js = order([{"product_id": Ctx.product_id, "quantity": 2}], "scn-041-" + uuid.uuid4().hex[:8])
    oid = js["data"]["id"]
    check("APP-R-041", "stock reserved", stock() == s0 - 2)
    body = {"status": "CANCELLED", "workflow_execution_id": "scn-wf-" + uuid.uuid4().hex[:8]}
    r1 = call("PATCH", f"/api/v1/admin/orders/{oid}/status", body, token=Ctx.admin)
    r2 = call("PATCH", f"/api/v1/admin/orders/{oid}/status", body, token=Ctx.admin)
    check("APP-R-041", "duplicate flagged", (r1[0], r2[0]) == (200, 200) and r1[2]["duplicate"] is False
          and r2[2]["duplicate"] is True)
    check("APP-R-041", "stock restored exactly once", stock() == s0)
    hist = call("GET", f"/api/v1/orders/{oid}", token=Ctx.customer)[2]["data"]["status_history"]
    check("APP-R-041", "single CANCELLED history entry", [h["status"] for h in hist] == ["PENDING", "CANCELLED"])


def s056(args):
    show("APP-R-056", "Detect and rectify API response-time degradation", {
        "initial condition": "optimized product-details handler; dev-simulated 120ms DB round-trip + 30ms processing",
        "trigger": "dev-only inefficient handler repeats the same product query 2,3,5,7,10 times per request",
        "detection signal": "avg/P95/P99 vs. historical baseline, 3 consecutive degraded windows",
        "expected behaviour": "~150ms baseline rising to ~1200ms; incident created; evidence from real traces",
        "expected event": "API_LATENCY_DEGRADATION (per window), PERFORMANCE_INCIDENT_DETECTED",
        "expected DB state": "api_latency_metrics windows, baseline unchanged by degraded windows, 1 incident",
        "future ML": "root-cause classification (NOT run in this phase)",
        "future action": "ACTION-056-02 proposed only; NOT executed",
        "verification": "after (future) action: 3 recovered windows + response correctness"})
    A = Ctx.admin
    pid, n, conc = Ctx.product_id, args.requests_per_window, 16
    call("POST", "/api/v1/dev/state", {"monitor_paused": True, "product_handler": "optimized", "repeat": 1,
                                       "query_delay_ms": 120, "base_delay_ms": 30}, token=A)
    call("POST", "/api/v1/dev/monitoring/close-window", token=A)   # flush leftovers from earlier scenarios

    def window(label):
        with ThreadPoolExecutor(conc) as ex:
            res = list(ex.map(lambda _: call("GET", f"/api/v1/products/{pid}")[0], range(n)))
        assert all(c == 200 for c in res), "unexpected non-200 during window"
        _, _, js = call("POST", "/api/v1/dev/monitoring/close-window", token=A)
        w = next((x for x in js["data"]["windows"] if x["endpoint"] == "/api/v1/products/{product_id}"), None)
        print(f"    {label:<22} avg={w['average_latency_ms']:>8.1f}ms p95={w['p95_latency_ms']:>8.1f}ms "
              f"p99={w['p99_latency_ms']:>8.1f}ms n={w['sample_count']} -> {w['degradation_status']}")
        return w

    print("  -- healthy baseline (optimized handler) --")
    for i in range(3):
        window(f"baseline window {i + 1}")
    print("  -- degradation (inefficient handler, measured, not injected into the database) --")
    stages = [2, 3, 5, 7, 10, 10, 10]
    last = None
    for i, repeat in enumerate(stages):
        call("POST", "/api/v1/dev/state", {"product_handler": "inefficient", "repeat": repeat}, token=A)
        last = window(f"stage {i + 1} ({repeat} queries)")
        _, _, inc = call("GET", "/api/v1/admin/performance/incidents?limit=5", token=A)
        if i >= 4 and any(x["endpoint"] == "/api/v1/products/{product_id}" and x["lifecycle_state"] == "OPEN"
                          for x in inc["data"]["items"]):
            break
    _, _, inc = call("GET", "/api/v1/admin/performance/incidents?limit=5", token=A)
    mine = [x for x in inc["data"]["items"] if x["endpoint"] == "/api/v1/products/{product_id}"
            and x["lifecycle_state"] == "OPEN"]
    check("APP-R-056", "sustained degradation -> incident", bool(mine))
    check("APP-R-056", "degraded to ~1s+ average", last and last["average_latency_ms"] > 900,
          f"(last avg {last and last['average_latency_ms']} ms)")
    if mine:
        i0 = mine[0]
        ev = i0["evidence"]
        print("    --- measured evidence (from stored trace spans) ---")
        print(f"    trace_id={ev.get('representative_trace_id')} total={ev.get('total_duration_ms')}ms "
              f"db_queries={ev.get('db_query_count')} db_ms={ev.get('db_duration_ms')} pattern={ev.get('pattern')}")
        print("    --- not performed in this phase ---")
        print(f"    ML diagnosis: {i0['diagnosis']['status']}; action_status: {i0['action_status']}; "
              f"proposed: {(i0['recommended_action'] or {}).get('action_id')} ({(i0['recommended_action'] or {}).get('status')})")
        check("APP-R-056", "repeated queries visible in trace evidence",
              ev.get("pattern") == "REPEATED_IDENTICAL_DB_QUERIES" and ev.get("db_query_count", 0) >= 5)
        check("APP-R-056", "no ML claim / nothing executed", i0["diagnosis"]["confidence"] is None
              and i0["action_status"] == "NOT_EXECUTED")
        _, _, base = call("GET", "/api/v1/admin/performance/baselines", token=A)
        b = next(x for x in base["data"]["items"] if x["endpoint"] == "/api/v1/products/{product_id}")
        check("APP-R-056", "baseline not contaminated by degraded windows",
              b["baseline_average_ms"] < 0.5 * last["average_latency_ms"], f"(baseline {b['baseline_average_ms']} ms)")
    call("POST", "/api/v1/dev/reset", token=A)   # restore optimized handler, unpause monitor
    print("    dev state reset (incident stays open; see docs/PERFORMANCE_MONITORING.md)")


SCENARIOS = {"APP-R-001": s001, "APP-R-002": s002, "APP-R-004": s004, "APP-R-020": s020, "APP-R-021": s021,
             "APP-R-030": s030, "APP-R-040": s040, "APP-R-041": s041, "APP-R-056": s056}


def main():
    global BASE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--enable", action="store_true", help="required: the runner is disabled by default")
    ap.add_argument("--base-url", default=os.getenv("SCENARIO_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--only", default="", help="comma separated rule ids")
    ap.add_argument("--admin-email", default=os.getenv("SEED_ADMIN_EMAIL", "admin@minishop.dev"))
    ap.add_argument("--admin-password", default=os.getenv("SEED_ADMIN_PASSWORD", "Admin@12345"))
    ap.add_argument("--requests-per-window", type=int, default=40)
    args = ap.parse_args()
    if not (args.enable or os.getenv("ENABLE_SCENARIO_RUNNER", "").lower() == "true"):
        sys.exit("Scenario runner is disabled by default. Re-run with --enable (development only).")
    BASE = args.base_url.rstrip("/")
    setup(args)
    chosen = [r.strip() for r in args.only.split(",") if r.strip()] or list(SCENARIOS)
    t0 = time.time()
    for rule in chosen:
        fn = SCENARIOS[rule]
        fn(args) if rule == "APP-R-056" else fn()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed in {time.time() - t0:.0f}s")
    for rule, _, name in failed:
        print(f"  FAILED {rule}: {name}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
