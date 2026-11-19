"""APP-R-056 predefined corrective-action registry.

Definitions only. NO executor is implemented in this phase: nothing here changes application
behaviour, and incidents never report an action as executed unless a future rectification engine
calls performance_service.record_action_execution(). Actions are predefined, tested-by-design,
reversible and never modify source code, DB-server configuration or infrastructure.
"""
from typing import Protocol

ACTIONS: dict[str, dict] = {
    "ACTION-056-01": {
        "name": "ELIMINATE_REDUNDANT_BUSINESS_PROCESSING",
        "title": "Eliminate redundant business processing",
        "description": "Switch to an approved optimized application handler that does not repeat the same "
                       "operation; business conditions are preserved.",
        "applicable_causes": ["REDUNDANT_BUSINESS_LOGIC", "REPEATED_INTERNAL_API_CALLS", "INEFFICIENT_DATA_PROCESSING"],
        "risk_level": "LOW", "reversible": True, "requires_approval": False,
    },
    "ACTION-056-02": {
        "name": "ENABLE_BATCHED_PRODUCT_LOOKUP",
        "title": "Optimize application data access",
        "description": "Replace repeated queries with the validated single/batched retrieval path "
                       "(application-level data access only; response correctness preserved).",
        "applicable_causes": ["REPEATED_DATABASE_QUERIES", "N_PLUS_ONE_QUERY_PATTERN"],
        "risk_level": "LOW", "reversible": True, "requires_approval": False,
    },
    "ACTION-056-03": {
        "name": "ENABLE_SAFE_READ_CACHE",
        "title": "Apply safe application-level caching",
        "description": "Cache eligible read results with approved TTL and invalidation; freshness and "
                       "authorization rules preserved.",
        "applicable_causes": ["INEFFICIENT_APPLICATION_CACHE", "EXCESSIVE_SERIALIZATION"],
        "risk_level": "MEDIUM", "reversible": True, "requires_approval": True,
    },
    "ACTION-056-04": {
        "name": "ACTIVATE_APPROVED_FALLBACK",
        "title": "Activate approved fallback",
        "description": "Serve a validated fallback response that explicitly marks stale/partial data. "
                       "Never returns incorrect business data merely to reduce latency.",
        "applicable_causes": ["SLOW_DOWNSTREAM_APPLICATION_DEPENDENCY"],
        "risk_level": "HIGH", "reversible": True, "requires_approval": True,
    },
}

COMMON_RESTRICTIONS = [
    "No automatic modification of source code",
    "No database-server configuration changes",
    "No infrastructure optimization",
    "No disabling of authentication or validation",
    "No unsafe caching",
    "No uncontrolled repeated remediation (each action at most once per incident)",
    "High-risk / medium-risk actions require approval",
]

for _a in ACTIONS.values():
    _a["restrictions"] = COMMON_RESTRICTIONS
    _a["verification_criteria"] = [
        "Average latency back within recovery_factor x baseline for N consecutive windows",
        "P95 and P99 recovered (when sample sizes are sufficient)",
        "Identified bottleneck no longer present in post-action traces",
        "Response schema unchanged and response values correct vs. reference",
        "No new application errors or data inconsistencies",
    ]
    _a["implemented"] = False  # executor intentionally not implemented in this phase

# Pattern -> action table used for *proposals* from MEASURED trace evidence (not an ML prediction).
EVIDENCE_PATTERN_TO_ACTION = {
    "REPEATED_IDENTICAL_DB_QUERIES": "ACTION-056-02",
    "REPEATED_QUERY_SHAPE_N_PLUS_ONE": "ACTION-056-02",
}


def propose_action(pattern: str) -> dict | None:
    action_id = EVIDENCE_PATTERN_TO_ACTION.get(pattern)
    if not action_id:
        return None
    a = ACTIONS[action_id]
    return {
        "action_id": action_id,
        "name": a["name"],
        "description": a["description"],
        "risk_level": a["risk_level"],
        "reversible": a["reversible"],
        "requires_approval": a["requires_approval"],
        "selected_by": "RULE_TABLE_FROM_MEASURED_TRACE_EVIDENCE",  # explicitly NOT an ML diagnosis
        "status": "PROPOSED",  # never "executed"
    }


class ActionExecutor(Protocol):
    """Interface for the future rectification engine (NOT implemented in this phase)."""

    async def execute(self, incident: dict, action_id: str) -> dict: ...

    async def rollback(self, incident: dict, action_id: str) -> dict: ...
