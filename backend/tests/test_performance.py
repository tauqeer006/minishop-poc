"""APP-R-056: measurement, windows, baselines, sustained detection, trace evidence."""
from datetime import timedelta

from app import dev_state
from app.services import latency_baseline_service as lbs
from app.utils.serialization import utcnow

EP = "/api/v1/products/{product_id}"
HEALTHY = [100 + (i % 10) for i in range(40)]   # avg 104.5, p99 109
DEGRADED = [400] * 40


async def _baseline(db, run_window, base, windows=2):
    for i in range(windows):
        s = base + timedelta(seconds=100 * i)
        await run_window(HEALTHY, s, s + timedelta(seconds=90))


async def test_latency_measurements_captured_per_route_template(client, product, db):
    for _ in range(3):
        assert (await client.get("/api/v1/products/prd_t1")).status_code == 200
    for _ in range(2):
        assert (await client.get("/api/v1/products")).status_code == 200
    detail = await db.latency_samples.find({"endpoint": EP}).to_list(None)
    assert len(detail) == 3 and all(s["http_method"] == "GET" and s["request_id"] and s["trace_id"] for s in detail)
    assert await db.latency_samples.count_documents({"endpoint": "/api/v1/products"}) == 2
    assert await db.latency_samples.count_documents({"endpoint": {"$regex": "prd_t1"}}) == 0  # no per-id identity
    assert "operation_timings" in detail[0] and detail[0]["db_query_count"] == 1


async def test_endpoints_keep_separate_metrics(db, run_window):
    base = utcnow() - timedelta(hours=3)
    a = await run_window([100] * 40, base, base + timedelta(seconds=60))
    b = await run_window([900] * 40, base, base + timedelta(seconds=60), endpoint="/api/v1/products")
    c = await run_window([300] * 40, base, base + timedelta(seconds=60), endpoint="/api/v1/orders", method="POST")
    assert (a["average_latency_ms"], b["average_latency_ms"], c["average_latency_ms"]) == (100, 900, 300)
    assert await db.api_latency_baselines.count_documents({}) == 3


def test_average_p95_p99_calculation():
    s = lbs.summarize([float(x) for x in range(1, 101)])
    assert (s["count"], s["avg"], s["p95"], s["p99"], s["min"], s["max"]) == (100, 50.5, 95, 99, 1, 100)


async def test_baseline_maintained_from_healthy_windows(db, run_window):
    base = utcnow() - timedelta(hours=3)
    await _baseline(db, run_window, base, windows=1)
    b = await lbs.get_baseline(db, EP, "GET")
    assert b["status"] == "LEARNING" and b["observation_count"] == 40
    await _baseline(db, run_window, base + timedelta(seconds=300), windows=1)
    b = await lbs.get_baseline(db, EP, "GET")
    assert b["status"] == "ACTIVE" and b["observation_count"] == 80 and b["baseline_version"] == 2
    assert abs(b["baseline_average_ms"] - 104.5) < 0.01


async def test_degraded_windows_do_not_contaminate_baseline(db, run_window):
    base = utcnow() - timedelta(hours=3)
    await _baseline(db, run_window, base)
    before = await lbs.get_baseline(db, EP, "GET")
    for k in range(2):  # 2 degraded windows: below the sustained threshold, still must not be learned
        s = base + timedelta(seconds=400 + 100 * k)
        w = await run_window(DEGRADED, s, s + timedelta(seconds=90))
        assert w["degradation_status"] == "DEGRADED"
    after = await lbs.get_baseline(db, EP, "GET")
    assert after["baseline_average_ms"] == before["baseline_average_ms"]
    assert after["observation_count"] == before["observation_count"]
    # a mildly elevated (suspect) window is also not learned
    s = base + timedelta(seconds=700)
    w = await run_window([140] * 40, s, s + timedelta(seconds=90))
    assert w["degradation_status"] == "SUSPECT"
    assert (await lbs.get_baseline(db, EP, "GET"))["observation_count"] == before["observation_count"]


async def test_sustained_degradation_creates_incident_with_preserved_metrics(db, run_window):
    base = utcnow() - timedelta(hours=3)
    await _baseline(db, run_window, base)
    for k in range(3):
        s = base + timedelta(seconds=400 + 100 * k)
        await run_window(DEGRADED, s, s + timedelta(seconds=90))
        count = await db.rectification_incidents.count_documents({})
        assert count == (1 if k == 2 else 0)  # only after 3 consecutive windows
    inc = await db.rectification_incidents.find_one({})
    assert inc["rule_id"] == "APP-R-056" and inc["endpoint"] == EP and inc["lifecycle_state"] == "OPEN"
    assert abs(inc["baseline_metrics"]["average_ms"] - 104.5) < 0.01       # original baseline preserved
    assert inc["degraded_metrics"]["average_ms"] == 400 and len(inc["degraded_metrics"]["windows"]) == 3
    assert inc["diagnosis"]["status"] == "AWAITING_ML_MODEL" and inc["diagnosis"]["confidence"] is None
    assert inc["action_status"] == "NOT_EXECUTED" and inc["action_attempts"] == []
    assert inc["ml_diagnosis_input"]["latency_features"]["average_trend_ms"] == [400, 400, 400]
    assert await db.application_events.count_documents({"event_type": "PERFORMANCE_INCIDENT_DETECTED"}) == 1
    assert await db.application_events.count_documents({"event_type": "API_LATENCY_DEGRADATION"}) == 3
    # a 4th degraded window must not open a duplicate incident
    s = base + timedelta(seconds=700)
    await run_window(DEGRADED, s, s + timedelta(seconds=90))
    assert await db.rectification_incidents.count_documents({"incident_type": "API_RESPONSE_TIME_DEGRADATION"}) == 1


async def test_isolated_slow_request_does_not_trigger_incident(db, run_window):
    base = utcnow() - timedelta(hours=3)
    await _baseline(db, run_window, base)
    for k in range(4):
        s = base + timedelta(seconds=400 + 100 * k)
        w = await run_window(HEALTHY[:39] + [9000], s, s + timedelta(seconds=90))
        assert w["degradation_status"] != "DEGRADED"   # p99 spikes, average does not
    assert await db.rectification_incidents.count_documents({}) == 0


async def test_insufficient_samples_never_alert(db, run_window):
    base = utcnow() - timedelta(hours=3)
    await _baseline(db, run_window, base)
    for k in range(3):  # 5 samples: far too few for percentile decisions
        s = base + timedelta(seconds=400 + 100 * k)
        w = await run_window([2000] * 5, s, s + timedelta(seconds=90), force=True)
        assert w["degradation_status"] == "INSUFFICIENT_DATA"
    for k in range(3):  # 15 samples: avg alone is not enough without reliable P95/P99
        s = base + timedelta(seconds=800 + 100 * k)
        w = await run_window([2000] * 15, s, s + timedelta(seconds=90), force=True)
        assert w["degradation_status"] == "SUSPECT"
    assert await db.rectification_incidents.count_documents({}) == 0


async def test_low_volume_endpoint_accumulates_instead_of_flushing(db, run_window):
    base = utcnow() - timedelta(hours=3)
    w = await run_window([100] * 8, base, base + timedelta(seconds=60))   # < p99-reliable minimum, not forced
    assert w is None  # kept for a longer aggregation window
    assert await db.latency_samples.count_documents({"processed": False}) == 8


async def test_repeated_db_queries_visible_in_real_trace_evidence(client, product, db, run_window):
    """Real execution: dev-only inefficient handler repeats the same product query 6 times."""
    dev_state.state.product_handler, dev_state.state.repeat = "inefficient", 6
    t0 = utcnow()
    for _ in range(3):
        r = await client.get("/api/v1/products/prd_t1")
        assert r.status_code == 200
    tid = r.headers["X-Trace-Id"]
    await db.latency_samples.update_many({}, {"$set": {"processed": True}})   # keep only synthetic samples below
    for i in range(2):
        s = t0 - timedelta(seconds=1000 - 100 * i)
        await run_window(HEALTHY, s, s + timedelta(seconds=90))
    for s, e in ((-5, 10), (10, 20), (20, 30)):
        await run_window(DEGRADED, t0 + timedelta(seconds=s), t0 + timedelta(seconds=e))

    inc = await db.rectification_incidents.find_one({"incident_type": "API_RESPONSE_TIME_DEGRADATION"})
    ev = inc["evidence"]
    assert ev["source"] == "MEASURED_TRACE_DATA" and ev["traces_analyzed"] == 3
    assert ev["pattern"] == "REPEATED_IDENTICAL_DB_QUERIES"
    assert ev["db_query_count"] == 6 and ev["repeated_identical_queries"][0]["count"] == 6
    assert "db" in ev["breakdown_ms"] and ev["db_duration_ms"] > 0
    assert tid in {*ev["trace_ids"]}
    spans = await db.trace_spans.find({"trace_id": tid}).to_list(None)
    assert sum(1 for s in spans if s["operation_type"] == "db") == 6
    assert any(s["operation_type"] == "business" and s["attributes"]["handler"] == "inefficient" for s in spans)
    # measured evidence -> proposal only; nothing executed, no ML claim
    assert inc["recommended_action"]["action_id"] == "ACTION-056-02"
    assert inc["recommended_action"]["status"] == "PROPOSED" and inc["action_status"] == "NOT_EXECUTED"
    assert inc["diagnosis"]["probable_cause"] is None
    assert inc["reference_response"]["product_id"] == "prd_t1"
