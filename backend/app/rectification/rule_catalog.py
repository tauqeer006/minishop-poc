"""The nine selected rules from the App-Level Self-Healing Rectification Rules catalogue.

This is documentation-as-data: IDs, titles, detection signals, ML-identification concepts and the
intended rule-based solution are preserved. `implemented_in` tells where each protection lives.
No ML is executed here.
"""

SELECTED_RULES: dict[str, dict] = {
    "APP-R-001": {
        "title": "Reject malformed requests before business logic",
        "detection": ["HTTP 400", "Schema validation failures", "Malformed JSON"],
        "ml_identification": "Classify malformed requests versus legitimate unusual input.",
        "solution": "Reject, stable error code (HTTP 400), no business logic executed, safe diagnostics.",
        "implemented_in": "observability/error_handlers.py (validation_error_handler)",
    },
    "APP-R-002": {
        "title": "Enforce API version compatibility",
        "detection": ["API contract mismatch", "Unsupported client version", "Version-specific errors"],
        "ml_identification": "Detect version-specific regressions.",
        "solution": "Adapter for legacy clients where one exists, otherwise explicit upgrade-required error (HTTP 426).",
        "implemented_in": "observability/middleware.py (evaluate_client_version), routes/orders.py (legacy cart adapter)",
    },
    "APP-R-004": {
        "title": "Prevent business-rule bypass",
        "detection": ["Business invariant violation", "Invalid business state", "Rejected transaction"],
        "ml_identification": "Identify unusual combinations of business-rule violations.",
        "solution": "Reject, audit event, preserve consistency, owner-notification interface.",
        "implemented_in": "services/order_service.py (BusinessRuleViolation, transactions, state machine)",
    },
    "APP-R-020": {
        "title": "Reject invalid domain data",
        "detection": ["Validation failures", "Invalid domain values", "Invariant violations"],
        "ml_identification": "Identify novel invalid-value patterns.",
        "solution": "Reject at the boundary, never persist, require corrected input.",
        "implemented_in": "models/schemas.py + observability/error_handlers.py (INVALID_DOMAIN_VALUE)",
    },
    "APP-R-021": {
        "title": "Prevent duplicate entity creation",
        "detection": ["Duplicate idempotency key", "Repeated submission", "Duplicate order attempts"],
        "ml_identification": "Identify duplicate submission patterns.",
        "solution": "Idempotency key + request fingerprint; identical retry returns the original order.",
        "implemented_in": "services/order_service.py (create_order/_replay) + unique index (user_id, idempotency_key)",
    },
    "APP-R-030": {
        "title": "Apply bounded retry with jitter",
        "detection": ["Timeout", "HTTP 5xx", "Transient connection error"],
        "ml_identification": "Classify transient versus persistent failures.",
        "solution": "Retry idempotent reads only, exponential backoff + full jitter, bounded budget, no retry storms.",
        "implemented_in": "utils/retry.py (retry_idempotent), used by product read routes only",
    },
    "APP-R-040": {
        "title": "Resolve optimistic-lock conflicts",
        "detection": ["Version-conflict exceptions", "Concurrent update conflicts"],
        "ml_identification": "Detect contention hotspots.",
        "solution": "Conditional updates on `version`, bounded retries where safe, never overwrite newer data.",
        "implemented_in": "services/product_service.py (update_product)",
    },
    "APP-R-041": {
        "title": "Prevent duplicate workflow execution",
        "detection": ["Duplicate workflow ID", "Repeated processing events"],
        "ml_identification": "Identify duplicate workflow execution patterns.",
        "solution": "Workflow execution id + state machine + conditional update; duplicates return previous result.",
        "implemented_in": "services/order_service.py (update_status)",
    },
    "APP-R-056": {
        "title": "Detect and rectify API response-time degradation",
        "detection": ["Sustained per-endpoint latency degradation vs. historical baseline (avg/P95/P99)",
                      "Consecutive degraded monitoring windows"],
        "ml_identification": "Future ML root-cause classification from latency features + trace evidence "
                             "(see rectification/ml_interface.py). NOT implemented in this phase.",
        "solution": "Predefined, reversible corrective actions (see action_registry.py), verified over multiple "
                    "windows, with rollback and engineering escalation on failure.",
        "implemented_in": "services/performance_service.py, services/latency_baseline_service.py, "
                          "observability/tracing.py (detection/evidence/verification only; actions NOT executed)",
    },
}
