import asyncio

from app import dev_state

H = {"Idempotency-Key": "key-aaaaaaaa-0001"}


def order_body(qty=2):
    return {"items": [{"product_id": "prd_t1", "quantity": qty}]}


async def test_successful_order(client, cust_h, product, db):
    r = await client.post("/api/v1/orders", headers={**cust_h, **H}, json=order_body(2))
    assert r.status_code == 201
    o = r.json()["data"]
    assert o["total_amount"] == 2000 and o["status"] == "PENDING" and o["id"].startswith("ORD-")
    assert (await db.products.find_one({"_id": "prd_t1"}))["stock_quantity"] == 8
    assert await db.application_events.count_documents({"event_type": "ORDER_CREATED"}) == 1


async def test_insufficient_stock_rejected(client, cust_h, product, db):  # APP-R-004
    r = await client.post("/api/v1/orders", headers={**cust_h, **H}, json=order_body(11))
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert await db.orders.count_documents({}) == 0
    assert (await db.products.find_one({"_id": "prd_t1"}))["stock_quantity"] == 10
    assert await db.audit_logs.count_documents({"action": "ORDER_REJECTED"}) == 1
    assert await db.application_events.count_documents({"event_type": "BUSINESS_INVARIANT_VIOLATION"}) == 1


async def test_duplicate_order_idempotency(client, cust_h, product, db):  # APP-R-021
    hdr = {**cust_h, **H}
    r1 = await client.post("/api/v1/orders", headers=hdr, json=order_body(1))
    r2 = await client.post("/api/v1/orders", headers=hdr, json=order_body(1))
    assert r1.status_code == 201 and r2.status_code == 200
    assert r1.json()["data"]["id"] == r2.json()["data"]["id"]
    assert await db.orders.count_documents({}) == 1
    assert (await db.products.find_one({"_id": "prd_t1"}))["stock_quantity"] == 9
    r3 = await client.post("/api/v1/orders", headers=hdr, json=order_body(3))  # same key, different payload
    assert r3.status_code == 409 and r3.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_concurrent_duplicate_checkout_creates_one_order(client, cust_h, product, db):
    hdr = {**cust_h, **H}
    rs = await asyncio.gather(*[client.post("/api/v1/orders", headers=hdr, json=order_body(1)) for _ in range(4)])
    assert all(r.status_code in (200, 201) for r in rs)
    assert await db.orders.count_documents({}) == 1
    assert (await db.products.find_one({"_id": "prd_t1"}))["stock_quantity"] == 9


async def test_transaction_rollback_after_injected_failure(client, cust_h, product, db):
    dev_state.state.checkout_failure = True
    r = await client.post("/api/v1/orders", headers={**cust_h, **H}, json=order_body(3))
    assert r.status_code == 500 and "Traceback" not in r.text
    assert await db.orders.count_documents({}) == 0
    assert (await db.products.find_one({"_id": "prd_t1"}))["stock_quantity"] == 10  # rolled back


async def test_malformed_checkout_json_is_400(client, cust_h, product, db):  # APP-R-001
    r = await client.post("/api/v1/orders", headers={**cust_h, **H, "Content-Type": "application/json"},
                          content=b'{"items": [ {"product_id": "prd_t1", "quantity": ')
    assert r.status_code == 400 and r.json()["error"]["code"] == "MALFORMED_JSON"
    r = await client.post("/api/v1/orders", headers={**cust_h, **H}, json={"items": "nope"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "REQUEST_SCHEMA_INVALID"
    r = await client.post("/api/v1/orders", headers={**cust_h, **H},
                          json={"items": [{"product_id": "prd_t1", "quantity": -1}]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_DOMAIN_VALUE"  # APP-R-020
    assert await db.orders.count_documents({}) == 0


async def test_invalid_status_transition_and_duplicate_workflow(client, cust_h, admin_h, product, db):
    o = (await client.post("/api/v1/orders", headers={**cust_h, **H}, json=order_body(2))).json()["data"]
    url = f"/api/v1/admin/orders/{o['id']}/status"
    bad = await client.patch(url, headers=admin_h, json={"status": "DELIVERED"})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    body = {"status": "CANCELLED", "workflow_execution_id": "wf-exec-1"}
    a = await client.patch(url, headers=admin_h, json=body)
    b = await client.patch(url, headers=admin_h, json=body)  # APP-R-041: same workflow triggered twice
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["duplicate"] is False and b.json()["duplicate"] is True
    assert (await db.products.find_one({"_id": "prd_t1"}))["stock_quantity"] == 10  # restocked exactly once
    stored = await db.orders.find_one({"_id": o["id"]})
    assert [h["status"] for h in stored["status_history"]] == ["PENDING", "CANCELLED"]
    assert await db.application_events.count_documents({"event_type": "DUPLICATE_WORKFLOW_EXECUTION"}) == 1


async def test_customer_cannot_see_other_orders(client, cust_h, admin_h, other_h, product, db):
    o = (await client.post("/api/v1/orders", headers={**cust_h, **H}, json=order_body(1))).json()["data"]
    assert (await client.get(f"/api/v1/orders/{o['id']}", headers=admin_h)).status_code == 200
    assert (await client.get(f"/api/v1/orders/{o['id']}", headers=other_h)).status_code == 404
