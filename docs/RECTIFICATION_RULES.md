# Selected rules and their relationship to the catalogue

The nine rules below come from the App-Level Self-Healing Rectification Rules catalogue. IDs, titles, detection
signals, ML-identification concepts and intended solutions are preserved in
`backend/app/rectification/rule_catalog.py` (the machine-readable copy used by the code). No other catalogue rule is
modified or removed by this POC.

| Rule | Title | Where it is enforced |
|---|---|---|
| APP-R-001 | Reject malformed requests before business logic | `observability/error_handlers.py` |
| APP-R-002 | Enforce API version compatibility | `observability/middleware.py`, `routes/orders.py` |
| APP-R-004 | Prevent business-rule bypass | `services/order_service.py` |
| APP-R-020 | Reject invalid domain data | `models/schemas.py`, `error_handlers.py` |
| APP-R-021 | Prevent duplicate entity creation | `services/order_service.py` |
| APP-R-030 | Apply bounded retry with jitter | `utils/retry.py` |
| APP-R-040 | Resolve optimistic-lock conflicts | `services/product_service.py` |
| APP-R-041 | Prevent duplicate workflow execution | `services/order_service.py` |
| APP-R-056 | Detect and rectify API response-time degradation | `services/performance_service.py`, `latency_baseline_service.py` |

Per rule: scenario, detection, expected behaviour, future ML identification and verification are in
[SCENARIOS.md](SCENARIOS.md).

## APP-R-056 placement in the catalogue
APP-R-056 is a new rule in the *performance and user experience* category and belongs **immediately after APP-R-055**
in Section 6 of the catalogue. APP-R-050 … APP-R-055 are untouched. It is intentionally **separate from APP-R-054**
(query optimisation): APP-R-054 concerns optimising a known slow query; APP-R-056 concerns *monitoring endpoint
response time against a historical baseline, diagnosing which internal operation consumes the time, selecting a
predefined application-level action and verifying recovery*. A repeated-query finding in APP-R-056 may recommend
a data-access action, but APP-R-056 does not tune queries, database servers, or infrastructure, and does not manage
traffic or request rates.

Suggested catalogue entry (for the document owner to paste after APP-R-055):

> **APP-R-056 — Detect and rectify API response-time degradation.** *Detection:* sustained per-endpoint
> avg/P95/P99 latency above historical baseline across consecutive windows. *ML identification:* classify the probable
> internal cause from latency features and trace/log evidence. *Solution:* select a predefined, reversible
> application-level action (optimised handler, batched data access, safe cache, approved fallback); verify recovery over
> multiple windows including response correctness; roll back and escalate on failure.
