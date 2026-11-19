# Controlled fault scenarios

Run all: `python scenarios/run_scenarios.py --enable` (development only; see README). Each scenario uses the real
HTTP API. Dev fault controls (`/api/v1/dev/*`) are admin-protected, in-memory only, mounted only when
`ENABLE_DEV_SCENARIOS=true` and `ENVIRONMENT != production`, and never disable authentication or validation.

Legend — **Today** = implemented and verified by tests/runner; **Future** = reserved for the next phase.

---
## APP-R-001 — Reject malformed requests before business logic
* **Fault:** customer submits malformed checkout JSON. **Reproduce:** `POST /orders` with body `{"items": [ {"product_id": "x", "quantity": ` (runner: `--only APP-R-001`).
* **Detection evidence:** HTTP 400, code `MALFORMED_JSON` (or `REQUEST_SCHEMA_INVALID`); event `REQUEST_VALIDATION_FAILURE` with `rule_id=APP-R-001`, `request_id`, `trace_id`.
* **Behaviour:** FastAPI's 422 is mapped to 400 in `validation_error_handler`; validation runs before the route, so no business code executes. Only `loc/type/msg` are stored (never submitted values).
* **Future ML:** classify malformed vs. legitimate-unusual input. **Future action:** reject (already enforced).
* **Verification:** order count and product stock unchanged.

## APP-R-002 — Enforce API version compatibility
* **Fault:** old frontend sends an unsupported contract. **Reproduce:** header `X-Client-Version: 0.5.0` on any `/api/*` call; `0.9.x` + `{"cart":[{"id","qty"}]}` for the legacy adapter.
* **Detection:** event `API_VERSION_MISMATCH` (426 `CLIENT_VERSION_UNSUPPORTED`, `Upgrade-Required` header) / `API_VERSION_ADAPTER_APPLIED`.
* **Behaviour:** ≥ `MIN_CLIENT_VERSION` (1.0.0) normal; ≥ `LEGACY_ADAPTER_MIN_VERSION` (0.9.0) adapted for checkout with `Deprecation` + `X-Client-Version-Adapter` headers; otherwise 426. The legacy `cart` shape is rejected for current clients — the contract is never silently changed. Missing header = unspecified (curl/Swagger) is allowed.
* **Future ML:** version-specific regressions. **Future action:** adapter / upgrade-required (enforced). **Verification:** supported clients keep working, unsupported get a stable error.

## APP-R-004 — Prevent business-rule bypass
* **Fault:** order quantity exceeds stock (or product inactive/missing). **Reproduce:** order 100 of a product with stock 20.
* **Detection:** 409 `INSUFFICIENT_STOCK`; event `BUSINESS_INVARIANT_VIOLATION` (rule APP-R-004); audit log `ORDER_REJECTED` (outcome `REJECTED:INSUFFICIENT_STOCK`).
* **Behaviour:** stock decremented with a conditional update (`stock_quantity >= qty`) inside a MongoDB transaction; any failure aborts the whole transaction; owner-notification interface (`OwnerNotifier`) only logs (no channel configured).
* **Future ML:** unusual violation combinations. **Future action:** reject + audit + notify. **Verification:** no order, stock unchanged.

## APP-R-020 — Reject invalid domain data
* **Fault:** negative quantity or price. **Reproduce:** order item `quantity: -3`; `POST /products` `price: -5`.
* **Detection:** 400 `INVALID_DOMAIN_VALUE`; event `DOMAIN_VALIDATION_FAILURE` (rule APP-R-020).
* **Behaviour:** rejected at the boundary; nothing persisted, so there is nothing to quarantine (the rejected payload shape is only in the event's `problems` list). **Future ML:** novel invalid-value patterns. **Verification:** collections contain no invalid data.

## APP-R-021 — Prevent duplicate entity creation
* **Fault:** same checkout submitted repeatedly. **Reproduce:** 3× `POST /orders` with one `Idempotency-Key`, then once more with a different body.
* **Detection:** event `DUPLICATE_ORDER_SUBMISSION` (`REPLAYED_PREVIOUS_ORDER` / `REJECTED_FINGERPRINT_MISMATCH`).
* **Behaviour:** unique index `(user_id, idempotency_key)` + SHA-256 request fingerprint. First 201, identical retries 200 with `Idempotent-Replay: true` and the original order; different payload → 409 `IDEMPOTENCY_KEY_REUSED`. Concurrent duplicates are resolved by the unique index (tested with 4 parallel requests).
* **Future ML:** duplicate-submission patterns. **Verification:** one order, stock decremented once.

## APP-R-030 — Bounded retry with jitter
* **Fault:** transient dependency failure during an idempotent read. **Reproduce:** `POST /dev/state {"read_fault_remaining": 2}` then `GET /products/{id}`; then `10`.
* **Detection:** events `TRANSIENT_DEPENDENCY_FAILURE` (each attempt), `TRANSIENT_DEPENDENCY_RECOVERED`.
* **Behaviour:** reads (product list/detail, order detail) retry up to `RETRY_MAX_ATTEMPTS` (3) with exponential backoff and **full jitter**, a total time budget (2 s) and a process-wide retry token bucket (anti retry-storm). Exhaustion → 503 `DEPENDENCY_UNAVAILABLE` + `Retry-After`. Checkout and other writes are never retried.
* **Future ML:** transient vs. persistent failures. **Verification:** read recovers with no duplicate business effects.

## APP-R-040 — Resolve optimistic-lock conflicts
* **Fault:** two admins edit the same product. **Reproduce:** two concurrent `PATCH /products/{id}` with the same `expected_version`.
* **Detection:** event `OPTIMISTIC_LOCK_CONFLICT`; one 200, one 409 `VERSION_CONFLICT`.
* **Behaviour:** `update_one({_id, version})` + `$inc version`. With `expected_version` the update is strict; without it the service performs bounded read-modify-conditional-write retries with jitter. `stock_delta` is commutative. Stale data never overwrites newer data.
* **Future ML:** contention hotspots. **Verification:** stock changed once, version +1.

## APP-R-041 — Prevent duplicate workflow execution
* **Fault:** same order-processing step triggered twice. **Reproduce:** `PATCH /admin/orders/{id}/status` twice with the same `workflow_execution_id`.
* **Detection:** event `DUPLICATE_WORKFLOW_EXECUTION`; second response has `duplicate: true`.
* **Behaviour:** state machine + execution-id recorded in `status_history` + conditional update on the current status inside a transaction → exactly one effect (e.g. restock on cancel happens once). Each order also has a unique `workflow_id`.
* **Future ML:** duplicate workflow patterns. **Verification:** single history entry, stock restored once.

---
## APP-R-056 — API response-time degradation (product details)
* **Initial condition:** optimized handler, dev-simulated 120 ms DB round-trip + 30 ms processing → baseline ≈ 150 ms.
* **Trigger:** `POST /dev/state {"product_handler":"inefficient","repeat":R}` — the development-only handler executes the **same product query R times** (R = 2, 3, 5, 7, 10 → ≈ 270, 390, 630, 870, 1230 ms). The slowness is real executed work + a configured simulated round-trip delay; **nothing is written into the metrics collections artificially**.
* **Detection signal:** per-window avg/P95/P99 vs. baseline (2×/2×/3×), 3 consecutive windows; event `API_LATENCY_DEGRADATION` per degraded window, `PERFORMANCE_INCIDENT_DETECTED` once.
* **Expected behaviour:** windows close via `POST /dev/monitoring/close-window` (same code as the periodic monitor, which the runner pauses for determinism). With the defaults stage 3, 4 and 5 are `DEGRADED` and the incident is created at stage 5.
* **Expected DB state:** `api_latency_metrics` windows; `api_latency_baselines` unchanged by degraded windows; `trace_spans` with N repeated `db` spans; one `rectification_incidents` document (`lifecycle_state=OPEN`, `diagnosis.status=AWAITING_ML_MODEL`, `action_status=NOT_EXECUTED`, `recommended_action.status=PROPOSED`).
* **Measured evidence vs. future ML vs. future action:** trace evidence (query count, DB ms, repeated identical query) is **measured**. The ML diagnosis input is stored but **no diagnosis is produced**. `ACTION-056-02` is a **rule-table proposal** from the measured pattern — **not executed**.
* **Future ML:** classify `REPEATED_DATABASE_QUERIES` from `ml_diagnosis_input`. **Future action:** `ACTION-056-02` via an `ActionExecutor`.
* **Verification criteria (defined, enforced by `verify_recovery`, exercised in tests):** ≥ 3 consecutive recovered windows (avg/P95/P99 ≤ 1.25× baseline), pattern no longer present in post-action traces, response schema and values match the reference captured at detection, zero errors; otherwise FAILED → rollback requested → ESCALATED.
* **Reference run (indicative, hardware dependent):** baseline ≈ 150–170 ms → ≈ 1.2 s at stage 5. The numbers in the task description are targets, not guaranteed results.
