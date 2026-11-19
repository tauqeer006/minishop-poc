"""APP-R-056: endpoint latency windows, sustained-degradation detection, trace evidence,
incident lifecycle, and post-rectification verification / escalation.

What is real in this phase: measurement, windows, baselines, threshold detection, trace evidence,
incident records, verification & escalation logic. What is NOT here: any ML diagnosis or any
automatic corrective-action execution (action_registry defines actions; nothing executes them).
"""
import asyncio
import hashlib
import json
import logging
import statistics
from collections import Counter
from datetime import timedelta

from app import database, dev_state
from app.config import settings
from app.observability.event_logger import log_event
from app.observability.tracing import breakdown_from_spans
from app.rectification import action_registry
from app.rectification.ml_interface import build_ml_input
from app.services import latency_baseline_service as lbs
from app.utils.serialization import new_id, public, utcnow

logger = logging.getLogger("minishop.performance")

EXCLUDED_PREFIXES = (
    "/api/v1/admin/performance", "/api/v1/admin/events", "/api/v1/admin/audit-logs", "/api/v1/dev",
)
OPEN_STATES = ("OPEN", "VERIFYING")
PRODUCT_DETAILS = "/api/v1/products/{product_id}"


class ActionNotAllowed(Exception):
    pass


def is_monitored(template: str) -> bool:
    return template.startswith("/api/") and not template.startswith(EXCLUDED_PREFIXES)


# --------------------------------------------------------------------------- window evaluation
def evaluate_window(summary: dict | None, baseline: dict | None, th: dict, error_rate: float) -> tuple[str, dict]:
    """Pure function. Returns (status, details). Status:
    INSUFFICIENT_DATA | LEARNING | NORMAL | SUSPECT | DEGRADED."""
    if summary is None or summary["count"] < settings.min_samples_window:
        return "INSUFFICIENT_DATA", {"reason": "not enough samples for a reliable window"}
    n = summary["count"]
    reliable95 = n >= settings.min_samples_p95
    reliable99 = n >= settings.min_samples_p99
    limit = th.get("absolute_limit_ms")
    abs_breach = bool(limit) and summary["avg"] > limit
    details: dict = {"percentile_p95_reliable": reliable95, "percentile_p99_reliable": reliable99,
                     "absolute_limit_ms": limit, "absolute_limit_breached": abs_breach,
                     "error_rate": round(error_rate, 4)}
    if baseline is None or baseline["status"] != "ACTIVE":
        return ("DEGRADED" if abs_breach else "LEARNING"), details

    b_avg = max(baseline["baseline_average_ms"], 1.0)
    b95 = max(baseline["baseline_p95_ms"], 1.0)
    b99 = max(baseline["baseline_p99_ms"], 1.0)
    r_avg, r95, r99 = summary["avg"] / b_avg, summary["p95"] / b95, summary["p99"] / b99
    details.update({"avg_ratio": round(r_avg, 3),
                    "p95_ratio": round(r95, 3) if reliable95 else None,
                    "p99_ratio": round(r99, 3) if reliable99 else None})
    # Relative degradation needs ALL criteria incl. percentiles; with too few samples the
    # percentiles are unreliable, so relative degradation cannot be declared (absolute limit still can).
    relative = (reliable95 and reliable99 and r_avg > th["avg_factor"]
                and r95 > th["p95_factor"] and r99 > th["p99_factor"])
    if relative or abs_breach:
        return "DEGRADED", details
    hf = th["healthy_factor"]
    if r_avg > hf or (reliable95 and r95 > hf) or (reliable99 and r99 > hf):
        return "SUSPECT", details
    return "NORMAL", details


async def _open_incident(db, endpoint: str, method: str) -> dict | None:
    return await db.rectification_incidents.find_one({
        "endpoint": endpoint, "http_method": method, "rule_id": "APP-R-056",
        "incident_type": "API_RESPONSE_TIME_DEGRADATION", "closed_at": None,
    })


async def close_window(db=None, now=None, force: bool = False) -> list[dict]:
    """Aggregate all unprocessed latency samples into one monitoring window per endpoint+method.
    Low-volume endpoints keep accumulating (longer effective window) until percentiles are reliable,
    up to max_accumulation_windows x window_seconds, then are flushed (possibly INSUFFICIENT_DATA)."""
    db = db if db is not None else database.get_db()
    cutoff = now or utcnow()
    docs = await db.latency_samples.find({"processed": False, "timestamp": {"$lte": cutoff}}).to_list(None)
    groups: dict[tuple, list] = {}
    for d in docs:
        groups.setdefault((d["endpoint"], d["http_method"]), []).append(d)
    max_age = timedelta(seconds=settings.window_seconds * settings.max_accumulation_windows)
    windows = []
    for (endpoint, method), g in groups.items():
        oldest = min(x["timestamp"] for x in g)
        # Low-volume endpoint: keep accumulating (longer effective window) until percentiles are reliable.
        if len(g) < settings.min_samples_p99 and not force and (cutoff - oldest) < max_age:
            continue
        window = await _process_group(db, endpoint, method, g, oldest, cutoff)
        await db.latency_samples.update_many(
            {"_id": {"$in": [x["_id"] for x in g]}}, {"$set": {"processed": True, "window_id": window["_id"]}})
        windows.append(window)
    return windows


async def _process_group(db, endpoint: str, method: str, docs: list[dict], w_start, w_end) -> dict:
    th = lbs.thresholds_for(f"{method} {endpoint}")
    ok = [d["duration_ms"] for d in docs if d["http_status"] < 500]
    errors = len(docs) - len(ok)
    error_rate = errors / len(docs)
    summary = lbs.summarize(ok) if ok else None
    baseline = await lbs.get_baseline(db, endpoint, method)
    status, details = evaluate_window(summary, baseline, th, error_rate)
    sm = summary or {"count": 0, "avg": 0, "p95": 0, "p99": 0, "min": 0, "max": 0}
    window = {
        "_id": new_id("win"), "endpoint": endpoint, "http_method": method,
        "window_start": w_start, "window_end": w_end,
        "sample_count": sm["count"], "error_count": errors,
        "average_latency_ms": sm["avg"], "p95_latency_ms": sm["p95"], "p99_latency_ms": sm["p99"],
        "min_latency_ms": sm["min"], "max_latency_ms": sm["max"],
        "baseline_average_ms": baseline["baseline_average_ms"] if baseline else None,
        "baseline_p95_ms": baseline["baseline_p95_ms"] if baseline else None,
        "baseline_p99_ms": baseline["baseline_p99_ms"] if baseline else None,
        "degradation_status": status, "evaluation": details, "created_at": utcnow(),
    }
    await db.api_latency_metrics.insert_one(window)

    open_inc = await _open_incident(db, endpoint, method)

    # Baselines learn ONLY from healthy windows and never while an incident is open.
    if status in ("LEARNING", "NORMAL") and summary and open_inc is None \
            and error_rate <= settings.max_error_rate_for_baseline:
        await lbs.update_baseline(db, endpoint, method, summary, w_start, w_end)

    if status == "DEGRADED":
        await log_event(
            "API_LATENCY_DEGRADATION", "WARNING", rule_id="APP-R-056", endpoint=endpoint,
            context={"http_method": method, "window_id": window["_id"],
                     "average_latency_ms": sm["avg"], "p95_latency_ms": sm["p95"], "p99_latency_ms": sm["p99"],
                     "baseline_average_ms": window["baseline_average_ms"], "sample_count": sm["count"],
                     "evaluation": details},
        )

    if open_inc is None:
        if status == "DEGRADED":
            n = th["consecutive_windows"]
            recent = await db.api_latency_metrics.find(
                {"endpoint": endpoint, "http_method": method, "degradation_status": {"$ne": "INSUFFICIENT_DATA"}}
            ).sort("window_end", -1).limit(n).to_list(None)
            if len(recent) == n and all(w["degradation_status"] == "DEGRADED" for w in recent):
                await create_incident(db, endpoint, method, list(reversed(recent)), baseline, th)
    else:
        await _track_open_incident(db, open_inc)
    return window


# --------------------------------------------------------------------------- trace evidence
async def build_evidence(db, endpoint: str, method: str, start, end, max_traces: int = 20) -> dict:
    """Derive MEASURED evidence from stored trace spans of the slowest requests in a time range."""
    roots = await db.trace_spans.find({
        "endpoint": endpoint, "http_method": method, "operation_type": "request",
        "end_time": {"$gte": start, "$lte": end},
    }).sort("duration_ms", -1).limit(max_traces).to_list(None)
    base = {"source": "MEASURED_TRACE_DATA", "traces_analyzed": 0, "trace_ids": [], "request_ids": [],
            "breakdown_ms": {}, "db_query_count": 0, "db_duration_ms": 0, "repeated_identical_queries": [],
            "pattern": "NO_TRACE_EVIDENCE"}
    if not roots:
        return base
    spans = await db.trace_spans.find({"trace_id": {"$in": [r["trace_id"] for r in roots]}}).to_list(None)
    by_trace: dict[str, list] = {}
    for s in spans:
        by_trace.setdefault(s["trace_id"], []).append(s)

    per_trace = []
    for r in roots:
        sp = by_trace[r["trace_id"]]
        dbs = [s for s in sp if s["operation_type"] == "db"]
        fps = Counter(s["attributes"].get("query_fingerprint") for s in dbs)
        sigs = Counter(s["attributes"].get("query_signature") for s in dbs)
        sig_of_fp = {s["attributes"].get("query_fingerprint"): s["attributes"].get("query_signature") for s in dbs}
        identical = sorted(
            ({"query_signature": sig_of_fp[fp], "count": c} for fp, c in fps.items() if c > 1),
            key=lambda x: -x["count"])
        shape_max_sig, shape_max = (sigs.most_common(1)[0] if sigs else (None, 0))
        distinct_values = len({s["attributes"].get("query_fingerprint") for s in dbs
                               if s["attributes"].get("query_signature") == shape_max_sig})
        per_trace.append({
            "root": r,
            "breakdown": breakdown_from_spans(sp, r["span_id"], r["duration_ms"]),
            "query_count": len(dbs),
            "db_ms": round(sum(s["duration_ms"] for s in dbs), 3),
            "identical": identical,
            "max_identical": max(fps.values()) if fps else 0,
            "shape_max": shape_max,
            "shape_distinct_values": distinct_values,
        })

    rep = per_trace[0]  # slowest trace
    med_identical = statistics.median(t["max_identical"] for t in per_trace)
    med_shape = statistics.median(t["shape_max"] for t in per_trace)
    med_distinct = statistics.median(t["shape_distinct_values"] for t in per_trace)
    if med_identical >= 3:
        pattern = "REPEATED_IDENTICAL_DB_QUERIES"
    elif med_shape >= 3 and med_distinct >= 3:
        pattern = "REPEATED_QUERY_SHAPE_N_PLUS_ONE"
    else:
        pattern = "NONE"
    total = rep["root"]["duration_ms"]
    dominant = max(rep["breakdown"], key=rep["breakdown"].get)
    return {
        "source": "MEASURED_TRACE_DATA",
        "traces_analyzed": len(per_trace),
        "trace_ids": [t["root"]["trace_id"] for t in per_trace[:5]],
        "request_ids": [t["root"]["request_id"] for t in per_trace[:5]],
        "representative_trace_id": rep["root"]["trace_id"],
        "representative_url_path": rep["root"]["attributes"].get("url_path"),
        "total_duration_ms": total,
        "breakdown_ms": rep["breakdown"],
        "db_query_count": rep["query_count"],
        "db_duration_ms": rep["db_ms"],
        "dominant_operation_type": dominant,
        "dominant_share": round(rep["breakdown"][dominant] / total, 3) if total else None,
        "repeated_identical_queries": rep["identical"],
        "median_db_query_count": statistics.median(t["query_count"] for t in per_trace),
        "max_identical_query_repeat": rep["max_identical"],
        "pattern": pattern,
    }


async def get_trace(db, trace_id: str) -> dict | None:
    spans = await db.trace_spans.find({"trace_id": trace_id}).sort("start_time", 1).to_list(None)
    if not spans:
        return None
    root = next((s for s in spans if s["operation_type"] == "request"), spans[0])
    dbs = [s for s in spans if s["operation_type"] == "db"]
    fps = Counter(s["attributes"].get("query_fingerprint") for s in dbs)
    sig_of_fp = {s["attributes"].get("query_fingerprint"): s["attributes"].get("query_signature") for s in dbs}
    return {
        "trace_id": trace_id,
        "endpoint": root["endpoint"],
        "http_method": root.get("http_method"),
        "request_id": root.get("request_id"),
        "total_duration_ms": root["duration_ms"],
        "spans": [public(s) for s in spans],
        "breakdown_ms": breakdown_from_spans(spans, root["span_id"], root["duration_ms"]),
        "db_query_count": len(dbs),
        "db_duration_ms": round(sum(s["duration_ms"] for s in dbs), 3),
        "repeated_queries": sorted(
            ({"query_signature": sig_of_fp[fp], "count": c} for fp, c in fps.items() if c > 1),
            key=lambda x: -x["count"]),
    }


# --------------------------------------------------------------------------- reference responses
def response_fingerprint(product_view: dict) -> str:
    """Hash of the response schema (key set) + stable business values (not stock/version/timestamps)."""
    stable = {k: product_view.get(k) for k in ("id", "name", "description", "price", "is_active")}
    stable["_keys"] = sorted(product_view.keys())
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()


async def _capture_reference(db, endpoint: str, evidence: dict) -> dict | None:
    if endpoint != PRODUCT_DETAILS or not evidence.get("representative_url_path"):
        return None
    pid = evidence["representative_url_path"].rstrip("/").rsplit("/", 1)[-1]
    doc = await db.products.find_one({"_id": pid})
    if not doc:
        return None
    return {"product_id": pid, "fingerprint": response_fingerprint(public(doc)), "captured_at": utcnow(),
            "source": "database_ground_truth_at_detection"}


async def _check_correctness(db, inc: dict, response_probe) -> dict:
    """Response schema + values must match the reference captured at detection time AND the
    database ground truth. `response_probe(product_id)` should call the real handler."""
    ref = inc.get("reference_response")
    if not ref:
        return {"checked": False, "ok": None, "detail": "no response reference available for this endpoint"}
    pid = ref["product_id"]
    if response_probe is None:
        from app.services import product_service  # real handler (honours the active handler mode)

        async def response_probe(product_id):
            return public(await product_service.get_product(product_id, include_inactive=True))
    try:
        live = await response_probe(pid)
    except Exception as exc:  # noqa: BLE001
        return {"checked": True, "ok": False, "detail": f"probe failed: {type(exc).__name__}"}
    truth = public(await db.products.find_one({"_id": pid}) or {})
    live_fp = response_fingerprint(live)
    ok = live_fp == ref["fingerprint"] and live_fp == response_fingerprint(truth)
    return {"checked": True, "ok": ok, "detail": "schema+values match reference" if ok else "response differs"}


# --------------------------------------------------------------------------- incidents
async def create_incident(db, endpoint: str, method: str, windows: list[dict], baseline: dict | None,
                          th: dict) -> dict:
    first, last = windows[0], windows[-1]
    base = baseline or {"baseline_average_ms": None, "baseline_p95_ms": None, "baseline_p99_ms": None,
                        "baseline_version": None}
    evidence = await build_evidence(db, endpoint, method, first["window_start"], last["window_end"])
    duration = (last["window_end"] - first["window_start"]).total_seconds()
    ml_input = build_ml_input(endpoint, method, base, windows, evidence, duration)
    reference = await _capture_reference(db, endpoint, evidence)
    b_avg = base["baseline_average_ms"]
    ratio = (last["average_latency_ms"] / b_avg) if b_avg else None
    severity = "CRITICAL" if ratio and ratio >= 5 else "HIGH" if ratio and ratio >= 3 else "WARNING"
    now = utcnow()
    rf = settings.recovery_factor
    doc = {
        "_id": new_id("inc"),
        "rule_id": "APP-R-056",
        "incident_type": "API_RESPONSE_TIME_DEGRADATION",
        "endpoint": endpoint, "http_method": method, "severity": severity,
        "detected_at": now,
        "degradation_started_at": first["window_start"],
        "degradation_duration_seconds": round(duration, 1),
        "baseline_metrics": {"average_ms": base["baseline_average_ms"], "p95_ms": base["baseline_p95_ms"],
                             "p99_ms": base["baseline_p99_ms"], "baseline_version": base["baseline_version"]},
        "degraded_metrics": {
            "average_ms": last["average_latency_ms"], "p95_ms": last["p95_latency_ms"],
            "p99_ms": last["p99_latency_ms"],
            "windows": [{"window_id": w["_id"], "window_start": w["window_start"], "window_end": w["window_end"],
                         "sample_count": w["sample_count"], "average_ms": w["average_latency_ms"],
                         "p95_ms": w["p95_latency_ms"], "p99_ms": w["p99_latency_ms"]} for w in windows],
        },
        "detection": {"method": "THRESHOLD_BASED", "thresholds": th, "consecutive_windows": len(windows)},
        # No ML model exists in this phase: diagnosis is explicitly pending, never fabricated.
        "diagnosis": {"status": "AWAITING_ML_MODEL", "probable_cause": None, "confidence": None,
                      "note": "No ML model has been run in this phase. See ml_diagnosis_input."},
        "ml_diagnosis_input": ml_input,
        "evidence": evidence,
        "trace_ids": evidence.get("trace_ids", []),
        "recommended_action": action_registry.propose_action(evidence["pattern"]),
        "action_status": "NOT_EXECUTED",
        "action_attempts": [],
        "verification_results": [],
        "recovery_status": "NOT_STARTED",
        "escalation_status": "NONE",
        "lifecycle_state": "OPEN",
        "resolved_at": None,
        "closed_at": None,
        "reference_response": reference,
        "expected_verification": {
            "required_consecutive_windows": settings.verification_windows,
            "max_verification_windows": settings.max_verification_windows,
            "average_max_ms": round(b_avg * rf, 1) if b_avg else None,
            "p95_max_ms": round(base["baseline_p95_ms"] * rf, 1) if base["baseline_p95_ms"] else None,
            "p99_max_ms": round(base["baseline_p99_ms"] * rf, 1) if base["baseline_p99_ms"] else None,
            "bottleneck_pattern_must_change_from": evidence["pattern"],
            "response_schema_unchanged": True, "response_values_match_reference": True,
            "no_new_application_errors": True,
        },
    }
    await db.rectification_incidents.insert_one(doc)
    await log_event(
        "PERFORMANCE_INCIDENT_DETECTED", "ERROR", rule_id="APP-R-056", endpoint=endpoint,
        context={"incident_id": doc["_id"], "http_method": method, "severity": severity,
                 "average_latency_ms": last["average_latency_ms"], "baseline_average_ms": b_avg,
                 "p95_latency_ms": last["p95_latency_ms"], "p99_latency_ms": last["p99_latency_ms"],
                 "trace_ids": doc["trace_ids"], "pattern": evidence["pattern"]},
    )
    return doc


async def _recent_windows_since(db, inc: dict, limit: int) -> list[dict]:
    wins = await db.api_latency_metrics.find({
        "endpoint": inc["endpoint"], "http_method": inc["http_method"],
        "window_end": {"$gt": inc["detected_at"]}, "degradation_status": {"$ne": "INSUFFICIENT_DATA"},
    }).sort("window_end", -1).limit(limit).to_list(None)
    return list(reversed(wins))


async def _track_open_incident(db, inc: dict) -> None:
    if inc["lifecycle_state"] in OPEN_STATES and inc["action_status"] == "EXECUTED":
        await verify_recovery(db, inc["_id"])
        return
    n = settings.verification_windows
    recent = await _recent_windows_since(db, inc, n)
    if len(recent) == n and all(w["degradation_status"] == "NORMAL" for w in recent):
        now = utcnow()
        upd = {"closed_at": now, "observed_recovery_at": now,
               "observed_recovery_note": "Latency observed back to normal; no corrective action was executed, "
                                         "so this is NOT a verified rectification."}
        if inc["lifecycle_state"] == "OPEN":
            upd.update({"lifecycle_state": "CLOSED_NO_ACTION", "recovery_status": "RECOVERED_WITHOUT_ACTION"})
        await db.rectification_incidents.update_one({"_id": inc["_id"]}, {"$set": upd})


async def record_action_execution(db, incident_id: str, action_id: str, executor: str,
                                  approved_by: str | None = None) -> dict:
    """Bookkeeping hook for the FUTURE rectification engine. Nothing in this phase calls it
    outside tests. Enforces: known action, approval for risky actions, at most once per action,
    bounded total attempts."""
    inc = await db.rectification_incidents.find_one({"_id": incident_id})
    if not inc or inc["lifecycle_state"] not in OPEN_STATES or inc.get("closed_at"):
        raise ActionNotAllowed("incident is not open")
    action = action_registry.ACTIONS.get(action_id)
    if not action:
        raise ActionNotAllowed("unknown action")
    if action["requires_approval"] and not approved_by:
        raise ActionNotAllowed("action requires approval")
    if any(a["action_id"] == action_id for a in inc["action_attempts"]):
        raise ActionNotAllowed("action already attempted for this incident")
    if len(inc["action_attempts"]) >= settings.max_action_attempts:
        raise ActionNotAllowed("action attempt budget exhausted")
    attempt = {"action_id": action_id, "executor": executor, "executed_at": utcnow(), "approved_by": approved_by}
    await db.rectification_incidents.update_one(
        {"_id": incident_id},
        {"$push": {"action_attempts": attempt},
         "$set": {"action_status": "EXECUTED", "lifecycle_state": "VERIFYING", "recovery_status": "VERIFYING"}})
    await log_event("RECTIFICATION_ACTION_OUTCOME", "INFO", rule_id="APP-R-056", endpoint=inc["endpoint"],
                    context={"incident_id": incident_id, "action_id": action_id, "outcome": "EXECUTED_RECORDED"})
    return await db.rectification_incidents.find_one({"_id": incident_id})


async def verify_recovery(db, incident_id: str, response_probe=None) -> dict:
    """Post-rectification verification over MULTIPLE windows. Never resolves on a single fast response."""
    inc = await db.rectification_incidents.find_one({"_id": incident_id})
    if not inc or inc["lifecycle_state"] not in OPEN_STATES or inc["action_status"] != "EXECUTED":
        return {"status": "NOT_APPLICABLE"}
    endpoint, method = inc["endpoint"], inc["http_method"]
    executed_at = inc["action_attempts"][-1]["executed_at"]
    wins = await db.api_latency_metrics.find({
        "endpoint": endpoint, "http_method": method, "window_end": {"$gt": executed_at},
        "degradation_status": {"$ne": "INSUFFICIENT_DATA"},
    }).sort("window_end", 1).to_list(None)
    need, rf, b = settings.verification_windows, settings.recovery_factor, inc["baseline_metrics"]

    def window_ok(w: dict) -> bool:
        return (w["average_latency_ms"] <= rf * b["average_ms"]
                and (w["sample_count"] < settings.min_samples_p95 or w["p95_latency_ms"] <= rf * b["p95_ms"])
                and (w["sample_count"] < settings.min_samples_p99 or w["p99_latency_ms"] <= rf * b["p99_ms"])
                and w.get("error_count", 0) == 0)

    latency_ok = len(wins) >= need and all(window_ok(w) for w in wins[-need:])
    bottleneck_ok, after = False, None
    if len(wins) >= need:
        after = await build_evidence(db, endpoint, method, wins[-need]["window_start"], wins[-1]["window_end"])
        bottleneck_ok = after["traces_analyzed"] > 0 and after["pattern"] != inc["evidence"]["pattern"]
    correctness = await _check_correctness(db, inc, response_probe)

    result = {
        "verified_at": utcnow(), "windows_observed_since_action": len(wins), "windows_required": need,
        "latency_recovered": latency_ok, "bottleneck_resolved": bottleneck_ok,
        "post_action_pattern": after["pattern"] if after else None,
        "response_correctness": correctness,
        "window_ids": [w["_id"] for w in wins[-need:]],
    }
    all_ok = latency_ok and bottleneck_ok and correctness["ok"] is True
    exhausted = len(wins) >= settings.max_verification_windows
    if all_ok:
        result["outcome"] = "RESOLVED"
        now = utcnow()
        await db.rectification_incidents.update_one(
            {"_id": incident_id},
            {"$push": {"verification_results": result},
             "$set": {"lifecycle_state": "RESOLVED", "recovery_status": "RESOLVED",
                      "resolved_at": now, "closed_at": now}})
        await log_event("PERFORMANCE_INCIDENT_VERIFIED", "INFO", rule_id="APP-R-056", endpoint=endpoint,
                        context={"incident_id": incident_id, "outcome": "RESOLVED"})
    elif correctness["ok"] is False or exhausted:
        result["outcome"] = "FAILED"
        await db.rectification_incidents.update_one({"_id": incident_id}, {"$push": {"verification_results": result}})
        await escalate(db, incident_id, reason="response_incorrect" if correctness["ok"] is False
                       else "latency_not_recovered_within_verification_budget")
    else:
        result["outcome"] = "PENDING"
        await db.rectification_incidents.update_one(
            {"_id": incident_id},
            {"$push": {"verification_results": result},
             "$set": {"lifecycle_state": "VERIFYING", "recovery_status": "VERIFYING"}})
    return result


async def escalate(db, incident_id: str, reason: str) -> dict:
    """Failed rectification: block further automatic attempts, request rollback, preserve evidence,
    open an engineering-investigation incident."""
    inc = await db.rectification_incidents.find_one({"_id": incident_id})
    now = utcnow()
    inv_id = new_id("inc")
    investigation = {
        "_id": inv_id, "rule_id": "APP-R-056", "incident_type": "ENGINEERING_INVESTIGATION",
        "parent_incident_id": incident_id, "endpoint": inc["endpoint"], "http_method": inc["http_method"],
        "severity": "HIGH", "detected_at": now, "reason": reason,
        "baseline_metrics": inc["baseline_metrics"], "degraded_metrics": inc["degraded_metrics"],
        "diagnosis": inc["diagnosis"], "ml_diagnosis_input": inc["ml_diagnosis_input"],
        "evidence": inc["evidence"], "trace_ids": inc["trace_ids"], "recommended_action": None,
        "action_status": "NOT_APPLICABLE", "action_attempts": inc["action_attempts"],
        "verification_results": inc["verification_results"],
        "recovery_status": "MANUAL_INVESTIGATION_REQUIRED", "escalation_status": "ESCALATED",
        "lifecycle_state": "ESCALATED", "resolved_at": None, "closed_at": now,
    }
    await db.rectification_incidents.insert_one(investigation)
    rollback_needed = bool(inc["action_attempts"])
    await db.rectification_incidents.update_one({"_id": incident_id}, {"$set": {
        "recovery_status": "FAILED", "escalation_status": "ESCALATED", "lifecycle_state": "ESCALATED",
        "further_automatic_attempts": "BLOCKED",
        "escalation": {"investigation_incident_id": inv_id, "escalated_at": now, "reason": reason},
        "rollback": {"status": "ROLLBACK_REQUESTED" if rollback_needed else "NOT_REQUIRED",
                     "requested_at": now, "note": "Rollback executor is part of the future engine."},
    }})
    await log_event("PERFORMANCE_INCIDENT_ESCALATED", "ERROR", rule_id="APP-R-056", endpoint=inc["endpoint"],
                    context={"incident_id": incident_id, "investigation_incident_id": inv_id, "reason": reason})
    return investigation


async def monitor_loop() -> None:
    """Closes a monitoring window every MONITOR_WINDOW_SECONDS."""
    while True:
        await asyncio.sleep(settings.window_seconds)
        if dev_state.active() and dev_state.state.monitor_paused:  # dev scenario runner only
            continue
        try:
            await close_window(database.get_db())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("window close failed")
