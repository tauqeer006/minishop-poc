import json


async def test_unsupported_client_version_gets_upgrade_required(client, cust_h, product, db):  # APP-R-002
    r = await client.get("/api/v1/products", headers={"X-Client-Version": "0.5.0"})
    assert r.status_code == 426 and r.json()["error"]["code"] == "CLIENT_VERSION_UNSUPPORTED"
    assert (await client.get("/api/v1/products", headers={"X-Client-Version": "1.0.0"})).status_code == 200
    assert (await client.get("/api/v1/products")).status_code == 200  # unspecified (curl/Swagger) allowed
    assert await db.application_events.count_documents({"event_type": "API_VERSION_MISMATCH"}) == 1


async def test_legacy_client_uses_adapter_but_unsupported_cannot(client, cust_h, product, db):
    hdr = {**cust_h, "Idempotency-Key": "legacy-key-0001", "X-Client-Version": "0.9.2"}
    r = await client.post("/api/v1/orders", headers=hdr, json={"cart": [{"id": "prd_t1", "qty": 2}]})
    assert r.status_code == 201 and r.headers["X-Client-Version-Adapter"] == "legacy-0.9-cart"
    assert r.json()["data"]["total_amount"] == 2000
    # the legacy contract is rejected for current clients (never silently changed)
    cur = await client.post("/api/v1/orders", json={"cart": [{"id": "prd_t1", "qty": 1}]},
                            headers={**cust_h, "Idempotency-Key": "legacy-key-0002", "X-Client-Version": "1.0.0"})
    assert cur.status_code == 400


async def test_structured_events_are_correlated_and_safe(client, db):
    rid = "req-test-12345"
    r = await client.post("/api/v1/auth/register", headers={"X-Request-ID": rid},
                          json={"name": "A", "email": "a@t.dev", "password": "Zq9!x"})
    assert r.status_code == 400 and r.headers["X-Request-ID"] == rid
    ev = await db.application_events.find_one({"request_id": rid})
    assert ev["event_type"] == "DOMAIN_VALIDATION_FAILURE" and ev["rule_id"] == "APP-R-020"
    assert ev["error_code"] == "INVALID_DOMAIN_VALUE" and ev["endpoint"] == "/api/v1/auth/register"
    assert ev["trace_id"] == r.headers["X-Trace-Id"] and ev["environment"] == "test"
    assert "Zq9!x" not in json.dumps(ev, default=str)  # submitted values are never stored


async def test_errors_use_standard_envelope_without_tracebacks(client):
    r = await client.get("/api/v1/does-not-exist")
    body = r.json()
    assert r.status_code == 404 and body["success"] is False and body["request_id"]
    assert "Traceback" not in r.text


async def test_trace_spans_cover_internal_operations(client, admin_h, db):
    r = await client.get("/api/v1/admin/orders", headers=admin_h)
    tid = r.headers["X-Trace-Id"]
    t = await client.get(f"/api/v1/admin/performance/traces/{tid}", headers=admin_h)
    data = t.json()["data"]
    types = {s["operation_type"] for s in data["spans"]}
    assert {"request", "auth", "authorization", "business", "db", "serialization"} <= types
    assert data["db_query_count"] >= 2 and data["total_duration_ms"] > 0
    assert set(data["breakdown_ms"]) >= {"auth", "db", "other"}


async def test_dev_endpoints_hidden_when_disabled(client, admin_h):
    from app.config import settings
    settings.dev_enabled = False
    try:
        assert (await client.get("/api/v1/dev/state", headers=admin_h)).status_code == 404
    finally:
        settings.dev_enabled = True
