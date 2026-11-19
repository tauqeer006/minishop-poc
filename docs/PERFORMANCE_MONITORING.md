# APP-R-056 — API response-time monitoring

Strict scope: **API response-time monitoring → historical baseline → sustained-degradation detection →
application-level diagnosis evidence → predefined corrective-action selection → verification → escalation.**
Not in scope: infrastructure/DB-server tuning, traffic or rate management, scaling.

## 1. Endpoint instrumentation
`ObservabilityMiddleware` (pure ASGI) wraps every HTTP request. It creates a `RequestContext` (request id,
W3C-compatible trace id), measures latency to the last response byte, resolves the **route template**
(`/api/v1/products/{product_id}`, never the concrete id) and stores a sample in `latency_samples`
(endpoint, method, duration, status, timestamp, request/trace id, DB query count/duration, per-operation timings).
Excluded: `/health`, docs, `/api/v1/admin/performance|events|audit-logs`, `/api/v1/dev`.

## 2. Windows and statistics
`performance_service.close_window()` (every `MONITOR_WINDOW_SECONDS`, default 60) aggregates unprocessed samples **per
endpoint+method** into `api_latency_metrics`: sample_count, average, P95, P99 (nearest-rank), min, max, error_count,
baseline values at evaluation time and `degradation_status` (`LEARNING | NORMAL | SUSPECT | DEGRADED | INSUFFICIENT_DATA`).
Only responses with status < 500 enter latency statistics; 5xx are counted separately.
Endpoints are never merged into a global average. **Low-volume endpoints** keep accumulating samples across windows
until P99 is reliable (`MIN_SAMPLES_P99`=30) or `MAX_ACCUMULATION_WINDOWS` (5) × window length passes.

## 3. Historical baselines (`api_latency_baselines`)
One baseline per endpoint+method: avg/P95/P99, `observation_count`, `calculation_period`, `last_updated`,
`baseline_version`, `status` (`LEARNING` until `BASELINE_MIN_OBSERVATIONS`=60 samples, then `ACTIVE`).
**Baselines learn only from healthy windows:** status `NORMAL` (all of avg/P95/P99 ≤ `HEALTHY_FACTOR`=1.25× baseline, or
`LEARNING`), error rate ≤ 5 %, **and no open incident on that endpoint**. `DEGRADED`, `SUSPECT`, low-volume windows and
anything during an incident are never learned, so an incident cannot raise its own baseline. Updates are
sample-weighted averages with capped weight (`BASELINE_MAX_WEIGHT`), so the baseline remains adaptive.

## 4. Degradation thresholds (all configurable)
Relative: `avg > 2×`, `P95 > 2×`, `P99 > 3×` baseline **simultaneously** (`AVG_FACTOR`, `P95_FACTOR`, `P99_FACTOR`),
requires reliable percentile sample sizes (P95 ≥ 20, P99 ≥ 30 samples). Absolute: `ABSOLUTE_LIMITS_JSON`
(e.g. `{"GET /api/v1/products/{product_id}": 3000}` on window average). Per-endpoint overrides:
`ENDPOINT_THRESHOLDS_JSON='{"POST /api/v1/orders": {"avg_factor": 3.0, "consecutive_windows": 4}}'`.
**Sustained:** an incident is created only after `CONSECUTIVE_WINDOWS` (3) consecutive `DEGRADED` windows
(`INSUFFICIENT_DATA` windows are skipped). A single slow request cannot create an incident (tested: a 9 s outlier moves
P99 but not P95/avg criteria); too-few-sample windows can never be `DEGRADED` by relative criteria (tested).

## 5. Distributed tracing
Spans (`trace_spans`): `request` (root), `auth`, `authorization`, `business` (service operations), `db` (every
MongoDB call via `TracedCollection`, with `query_signature` = shape and `query_fingerprint` = shape + values),
`serialization` (response building), `dependency`/`data_processing` (reserved types). `X-Request-ID`, `X-Trace-Id`
tie logs (`application_events.trace_id`), latency samples and spans together. Retention: sampled traces
(`TRACE_SAMPLE_RATE`, default 0.2) live `TRACE_TTL_HOURS`=24 h; slow (≥ `TRACE_SLOW_MS`) and 5xx traces are always kept for
`TRACE_KEEP_TTL_DAYS`=7 (MongoDB TTL index on `expire_at`). Breakdown uses **exclusive (self) time** per operation type so
nested spans are not double counted: e.g. total 1200 ms = db 980 + auth 12 + serialization 45 + business 80 + other 83.

## 6. Root-cause evidence (measured) and ML diagnosis (future)
On incident creation `build_evidence()` analyses the slowest traces in the degraded windows: breakdown by operation
type, dominant operation, DB query count/duration, repeated identical queries (same fingerprint) and repeated query
shapes with different values (N+1 candidate), producing `pattern` ∈ `REPEATED_IDENTICAL_DB_QUERIES |
REPEATED_QUERY_SHAPE_N_PLUS_ONE | NONE | NO_TRACE_EVIDENCE`. This is **measured evidence, not an ML result**.
The incident also stores `ml_diagnosis_input` (latency features + execution evidence) and
`diagnosis = {status: "AWAITING_ML_MODEL", probable_cause: null, confidence: null}`.
Future output contract (`rectification/ml_interface.py::FaultDiagnosis`):
```json
{"rule_id":"APP-R-056","fault_type":"API_RESPONSE_TIME_DEGRADATION","probable_cause":"REPEATED_DATABASE_QUERIES",
 "confidence":0.96,"recommended_action":"ACTION-056-02","requires_approval":false}
```
(example of the interface only — no model exists in this phase). Probable causes: REDUNDANT_BUSINESS_LOGIC,
REPEATED_DATABASE_QUERIES, N_PLUS_ONE_QUERY_PATTERN, INEFFICIENT_DATA_PROCESSING, REPEATED_INTERNAL_API_CALLS,
EXCESSIVE_SERIALIZATION, SLOW_DOWNSTREAM_APPLICATION_DEPENDENCY, INEFFICIENT_APPLICATION_CACHE, UNKNOWN_APPLICATION_BOTTLENECK.

## 7. Corrective-action registry (`rectification/action_registry.py`) — definitions only
| ID | Action | Risk | Approval |
|---|---|---|---|
| ACTION-056-01 | Eliminate redundant business processing (approved optimised handler) | LOW | no |
| ACTION-056-02 | Optimise application data access (`ENABLE_BATCHED_PRODUCT_LOOKUP`) | LOW | no |
| ACTION-056-03 | Safe application-level caching (TTL + invalidation, auth-aware) | MEDIUM | yes |
| ACTION-056-04 | Approved fallback (explicitly marked stale/partial) | HIGH | yes |

All `implemented: false`: **no executor exists**. Restrictions: no source-code changes, no DB-server/infrastructure
changes, never disable auth/validation, no unsafe caching, each action at most once per incident
(`record_action_execution` enforces this plus an attempt budget and approval for risky actions). The incident's
`recommended_action` (status `PROPOSED`) comes from a rule table over *measured* evidence patterns, labelled
`selected_by: RULE_TABLE_FROM_MEASURED_TRACE_EVIDENCE`.

## 8. Verification (`verify_recovery`)
After a (future) action is recorded, each new window triggers verification. Resolution requires **all** of:
≥ `VERIFICATION_WINDOWS` (3) post-action windows with avg/P95/P99 ≤ `RECOVERY_FACTOR` (1.25) × the *original* baseline and no
errors; the bottleneck pattern absent from post-action traces; response schema + stable values equal to the reference captured at
detection **and** current database truth. One fast response never resolves an incident. Recovery without any executed
action is recorded as `CLOSED_NO_ACTION / RECOVERED_WITHOUT_ACTION` (never as a rectification).

## 9. Rollback and escalation
If a response is incorrect, or recovery does not happen within `MAX_VERIFICATION_WINDOWS` (6): `recovery_status=FAILED`,
further automatic attempts `BLOCKED`, rollback `ROLLBACK_REQUESTED` (executor is part of the future engine), original/degraded
metrics, ML input, trace ids and verification history are preserved, an `ENGINEERING_INVESTIGATION` incident is created, and
the original incident ends `ESCALATED`. Final states: `RESOLVED`, `FAILED`/`ESCALATED` (recorded as `recovery_status=FAILED`,
`lifecycle_state=ESCALATED`, `escalation_status=ESCALATED`).

## 10. Reproducing
`python scenarios/run_scenarios.py --enable --only APP-R-056`, then open *Admin → Performance*.
Unit-level proofs: `pytest tests/test_performance.py tests/test_rectification_scenarios.py`.
