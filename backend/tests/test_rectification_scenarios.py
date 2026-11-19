"""APP-R-056 incident lifecycle: verification, rollback request, escalation (logic tests with a
controlled timeline and synthetic traces; the real-execution path is covered in test_performance.py)."""
from datetime import timedelta

import pytest

from app.services import performance_service as ps
from app.utils.serialization import utcnow

HEALTHY = [100 + (i % 10) for i in range(40)]
DEGRADED = [400] * 40


@pytest.fixture
def base():
    return utcnow() - timedelta(hours=5)


async def open_incident(db, run_window, insert_trace, product, base):
    for i in range(2):
        s = base + timedelta(seconds=100 * i)
        await run_window(HEALTHY, s, s + timedelta(seconds=90))
    for k in range(3):
        s = base + timedelta(seconds=300 + 100 * k)
        await insert_trace(s + timedelta(seconds=45), queries=8, total_ms=400, repeated=True)
        await run_window(DEGRADED, s, s + timedelta(seconds=90))
    inc = await db.rectification_incidents.find_one({"incident_type": "API_RESPONSE_TIME_DEGRADATION"})
    assert inc["evidence"]["pattern"] == "REPEATED_IDENTICAL_DB_QUERIES"
    # place the incident on the controlled (fake) timeline
    await db.rectification_incidents.update_one(
        {"_id": inc["_id"]}, {"$set": {"detected_at": base + timedelta(seconds=595)}})
    return inc["_id"]


async def execute_action(db, inc_id, base):
    await ps.record_action_execution(db, inc_id, "ACTION-056-02", executor="test-engine")
    await db.rectification_incidents.update_one(
        {"_id": inc_id}, {"$set": {"action_attempts.0.executed_at": base + timedelta(seconds=600)}})


async def post_window(db, run_window, insert_trace, base, k, durations, queries, total, repeated):
    s = base + timedelta(seconds=700 + 100 * k)
    await insert_trace(s + timedelta(seconds=45), queries=queries, total_ms=total, repeated=repeated)
    return await run_window(durations, s, s + timedelta(seconds=90))


async def test_recovery_requires_multiple_windows_then_resolves(db, run_window, insert_trace, product, base):
    inc_id = await open_incident(db, run_window, insert_trace, product, base)
    await execute_action(db, inc_id, base)
    await post_window(db, run_window, insert_trace, base, 0, HEALTHY, 1, 100, False)   # one fast window
    inc = await db.rectification_incidents.find_one({"_id": inc_id})
    assert inc["lifecycle_state"] == "VERIFYING" and inc["resolved_at"] is None       # NOT resolved yet
    assert inc["verification_results"][-1]["outcome"] == "PENDING"
    for k in (1, 2):
        await post_window(db, run_window, insert_trace, base, k, HEALTHY, 1, 100, False)
    inc = await db.rectification_incidents.find_one({"_id": inc_id})
    last = inc["verification_results"][-1]
    assert inc["lifecycle_state"] == "RESOLVED" and inc["recovery_status"] == "RESOLVED" and inc["resolved_at"]
    assert last["latency_recovered"] and last["bottleneck_resolved"] and last["response_correctness"]["ok"] is True
    assert inc["baseline_metrics"]["average_ms"] > 0 and inc["degraded_metrics"]["average_ms"] == 400  # preserved


async def test_failed_recovery_stops_attempts_and_escalates(db, run_window, insert_trace, product, base):
    inc_id = await open_incident(db, run_window, insert_trace, product, base)
    await execute_action(db, inc_id, base)
    for k in range(6):  # latency never recovers within the verification budget
        await post_window(db, run_window, insert_trace, base, k, DEGRADED, 8, 400, True)
    inc = await db.rectification_incidents.find_one({"_id": inc_id})
    assert inc["recovery_status"] == "FAILED" and inc["escalation_status"] == "ESCALATED"
    assert inc["lifecycle_state"] == "ESCALATED" and inc["further_automatic_attempts"] == "BLOCKED"
    assert inc["rollback"]["status"] == "ROLLBACK_REQUESTED"
    inv = await db.rectification_incidents.find_one({"incident_type": "ENGINEERING_INVESTIGATION"})
    assert inv["parent_incident_id"] == inc_id and inv["evidence"]["pattern"] == "REPEATED_IDENTICAL_DB_QUERIES"
    assert inv["baseline_metrics"] == inc["baseline_metrics"] and inv["trace_ids"] == inc["trace_ids"]
    with pytest.raises(ps.ActionNotAllowed):   # no further automatic attempts
        await ps.record_action_execution(db, inc_id, "ACTION-056-01", executor="test-engine")
    assert await db.rectification_incidents.count_documents({"incident_type": "ENGINEERING_INVESTIGATION"}) == 1


async def test_same_action_cannot_be_repeated_and_risky_needs_approval(db, run_window, insert_trace, product, base):
    inc_id = await open_incident(db, run_window, insert_trace, product, base)
    with pytest.raises(ps.ActionNotAllowed):
        await ps.record_action_execution(db, inc_id, "ACTION-056-04", executor="e")        # needs approval
    await ps.record_action_execution(db, inc_id, "ACTION-056-02", executor="e")
    with pytest.raises(ps.ActionNotAllowed):
        await ps.record_action_execution(db, inc_id, "ACTION-056-02", executor="e")        # no repeat


async def test_incorrect_response_blocks_resolution(db, run_window, insert_trace, product, base):
    inc_id = await open_incident(db, run_window, insert_trace, product, base)
    await execute_action(db, inc_id, base)
    await db.products.update_one({"_id": "prd_t1"}, {"$set": {"price": 1}})   # response no longer matches reference
    for k in range(3):
        await post_window(db, run_window, insert_trace, base, k, HEALTHY, 1, 100, False)
    inc = await db.rectification_incidents.find_one({"_id": inc_id})
    assert inc["lifecycle_state"] == "ESCALATED" and inc["recovery_status"] == "FAILED"
    assert inc["verification_results"][-1]["response_correctness"]["ok"] is False


async def test_recovery_without_action_is_not_reported_as_rectification(db, run_window, insert_trace, product, base):
    inc_id = await open_incident(db, run_window, insert_trace, product, base)
    for k in range(3):
        await post_window(db, run_window, insert_trace, base, k, HEALTHY, 1, 100, False)
    inc = await db.rectification_incidents.find_one({"_id": inc_id})
    assert inc["lifecycle_state"] == "CLOSED_NO_ACTION" and inc["action_status"] == "NOT_EXECUTED"
    assert inc["recovery_status"] == "RECOVERED_WITHOUT_ACTION" and inc["resolved_at"] is None
