async def test_register_and_login(client):
    r = await client.post("/api/v1/auth/register",
                          json={"name": "New", "email": "new@t.dev", "password": "Password123"})
    assert r.status_code == 201
    assert r.json()["data"]["user"]["role"] == "customer"
    assert "password_hash" not in r.text
    r = await client.post("/api/v1/auth/login", json={"email": "new@t.dev", "password": "Password123"})
    assert r.status_code == 200
    token = r.json()["data"]["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["data"]["email"] == "new@t.dev"


async def test_duplicate_email_and_bad_login(client, db):
    body = {"name": "X", "email": "dup@t.dev", "password": "Password123"}
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 201
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 409
    r = await client.post("/api/v1/auth/login", json={"email": "dup@t.dev", "password": "wrong-password"})
    assert r.status_code == 401
    assert await db.application_events.count_documents({"event_type": "AUTHENTICATION_FAILURE"}) >= 1


async def test_customer_cannot_use_admin_endpoints(client, cust_h):
    assert (await client.get("/api/v1/admin/dashboard", headers=cust_h)).status_code == 403
    assert (await client.get("/api/v1/admin/performance/endpoints", headers=cust_h)).status_code == 403
    assert (await client.post("/api/v1/products", headers=cust_h, json={
        "name": "x", "price": 100, "stock_quantity": 1})).status_code == 403
    assert (await client.get("/api/v1/admin/dashboard")).status_code == 401
