import asyncio


async def test_admin_creates_and_validates_product(client, admin_h, db):
    ok = await client.post("/api/v1/products", headers=admin_h,
                           json={"name": "Cable", "description": "usb", "price": 500, "stock_quantity": 5})
    assert ok.status_code == 201 and ok.json()["data"]["version"] == 1
    bad = await client.post("/api/v1/products", headers=admin_h,
                            json={"name": "Bad", "price": -5, "stock_quantity": 5})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_DOMAIN_VALUE"  # APP-R-020
    assert await db.products.count_documents({"name": "Bad"}) == 0
    assert await db.application_events.count_documents({"event_type": "DOMAIN_VALIDATION_FAILURE"}) == 1


async def test_list_search_and_detail(client, product):
    r = await client.get("/api/v1/products", params={"search": "mouse"})
    assert r.json()["data"]["total"] == 1
    d = await client.get("/api/v1/products/prd_t1")
    assert d.json()["data"]["id"] == "prd_t1" and d.json()["data"]["price"] == 1000
    assert (await client.get("/api/v1/products/nope")).status_code == 404


async def test_concurrent_stock_update_conflict(client, admin_h, product):
    """APP-R-040: two admins use the same expected_version; exactly one wins, no lost update."""
    body = {"stock_delta": -1, "expected_version": 1}
    r1, r2 = await asyncio.gather(
        client.patch("/api/v1/products/prd_t1", headers=admin_h, json=body),
        client.patch("/api/v1/products/prd_t1", headers=admin_h, json=body))
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [200, 409]
    final = (await client.get("/api/v1/products/prd_t1")).json()["data"]
    assert final["stock_quantity"] == 9 and final["version"] == 2


async def test_transient_read_failure_is_retried(client, product, db):
    """APP-R-030: injected transient failures are retried (bounded, jittered) for idempotent reads."""
    from app import dev_state
    dev_state.state.read_fault_remaining = 2
    r = await client.get("/api/v1/products/prd_t1")
    assert r.status_code == 200
    assert await db.application_events.count_documents({"event_type": "TRANSIENT_DEPENDENCY_FAILURE"}) == 2
    dev_state.state.read_fault_remaining = 10  # more than the retry budget
    r = await client.get("/api/v1/products/prd_t1")
    assert r.status_code == 503 and r.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
