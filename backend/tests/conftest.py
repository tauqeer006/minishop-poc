"""Test fixtures. Tests run against a DISPOSABLE database (minishop_test_<random>) on the same
MongoDB replica set (transactions need one) and drop it afterwards. They never touch the
seeded `minishop` development database."""
import os
import uuid

os.environ["ENVIRONMENT"] = "test"
os.environ["ENABLE_DEV_SCENARIOS"] = "true"
os.environ["MONITOR_ENABLED"] = "false"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["TRACE_SAMPLE_RATE"] = "1.0"

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402

from app import database, dev_state  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.utils.security import hash_password  # noqa: E402
from app.utils.serialization import utcnow  # noqa: E402

TEST_MONGO_URI = os.getenv("TEST_MONGO_URI", "mongodb://database:27017/?replicaSet=rs0")
settings.bcrypt_rounds = 4
settings.trace_sample_rate = 1.0
settings.dev_enabled = True


@pytest_asyncio.fixture
async def db():
    name = f"minishop_test_{uuid.uuid4().hex[:10]}"
    assert name.startswith("minishop_test_")  # safety: never a development database
    d = database.init_db(TEST_MONGO_URI, name)
    await database.wait_for_primary(30)
    await database.ensure_indexes(d)
    dev_state.state.reset()
    yield d
    await database.get_client().drop_database(name)
    await database.close_db()


@pytest_asyncio.fixture
async def client(db):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_user(db, uid, email, role):
    await db.users.insert_one({"_id": uid, "name": uid, "email": email, "role": role,
                               "password_hash": await hash_password("Passw0rd!x"), "created_at": utcnow()})


async def _login(client, email):
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "Passw0rd!x"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest_asyncio.fixture
async def admin_h(client, db):
    await _make_user(db, "usr_admin", "admin@t.dev", "admin")
    return await _login(client, "admin@t.dev")


@pytest_asyncio.fixture
async def cust_h(client, db):
    await _make_user(db, "usr_cust", "cust@t.dev", "customer")
    return await _login(client, "cust@t.dev")


@pytest_asyncio.fixture
async def run_window(db):
    """Insert latency samples with controlled timestamps (logic tests) and close a monitoring window."""
    from datetime import timedelta
    from app.services import performance_service

    async def _run(durations, start, end, endpoint="/api/v1/products/{product_id}", method="GET",
                   status=200, force=False):
        n = len(durations)
        step = (end - start).total_seconds() / (n + 1)
        docs = [{"_id": f"smp_{uuid.uuid4().hex[:12]}", "endpoint": endpoint, "http_method": method,
                 "duration_ms": float(d), "http_status": status,
                 "timestamp": start + timedelta(seconds=step * (i + 1)), "request_id": f"r{i}",
                 "trace_id": "t", "processed": False, "expire_at": end + timedelta(days=1)}
                for i, d in enumerate(durations)]
        await db.latency_samples.insert_many(docs)
        wins = await performance_service.close_window(db, now=end, force=force)
        match = [w for w in wins if w["endpoint"] == endpoint and w["http_method"] == method]
        return match[0] if match else None

    return _run


@pytest_asyncio.fixture
async def insert_trace(db):
    """Insert a synthetic trace (root + business + N db spans) for verification-logic tests."""
    from datetime import timedelta

    async def _insert(end, queries, total_ms, repeated=True, endpoint="/api/v1/products/{product_id}"):
        tid, root = uuid.uuid4().hex, uuid.uuid4().hex[:16]
        base = {"trace_id": tid, "request_id": f"req-{tid[:6]}", "endpoint": endpoint, "http_method": "GET",
                "environment": "test", "status": "OK", "expire_at": end + timedelta(days=1)}
        per = round(total_ms * 0.9 / max(queries, 1), 3)
        spans = [{**base, "_id": f"spn_{uuid.uuid4().hex[:12]}", "span_id": root, "parent_span_id": None,
                  "operation_name": f"GET {endpoint}", "operation_type": "request", "duration_ms": float(total_ms),
                  "start_time": end - timedelta(milliseconds=total_ms), "end_time": end,
                  "attributes": {"url_path": "/api/v1/products/prd_t1"}}]
        for i in range(queries):
            fp = "same" if repeated else f"fp{i}"
            spans.append({**base, "_id": f"spn_{uuid.uuid4().hex[:12]}", "span_id": uuid.uuid4().hex[:16],
                          "parent_span_id": root, "operation_name": "db.products.find_one", "operation_type": "db",
                          "duration_ms": per, "start_time": end, "end_time": end,
                          "attributes": {"query_signature": "products.find_one(_id)", "query_fingerprint": fp}})
        await db.trace_spans.insert_many(spans)
        return tid

    return _insert


@pytest_asyncio.fixture
async def other_h(client, db):
    await _make_user(db, "usr_other", "other@t.dev", "customer")
    return await _login(client, "other@t.dev")


@pytest_asyncio.fixture
async def product(db):
    now = utcnow()
    doc = {"_id": "prd_t1", "name": "Test Mouse", "description": "d", "price": 1000, "stock_quantity": 10,
           "is_active": True, "version": 1, "created_at": now, "updated_at": now}
    await db.products.insert_one(doc)
    return doc
