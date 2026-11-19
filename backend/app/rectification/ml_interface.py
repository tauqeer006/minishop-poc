"""Future ML integration contract (NO model, NO predictions in this phase).

Where the model plugs in:
  1. performance_service.create_incident() stores `ml_diagnosis_input` (see build_ml_input) on every
     APP-R-056 incident with diagnosis.status = AWAITING_ML_MODEL.
  2. A future component implements `FaultIdentifier.identify()` and writes a validated
     `FaultDiagnosis` into incident["diagnosis"].
  3. A future rectification engine maps `recommended_action` through action_registry and runs the
     action via an `ActionExecutor`, then calls performance_service.verify_recovery().
General-rule features come from `extract_general_features()` (application_events aggregates).
"""
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, Field

ProbableCause = Literal[
    "REDUNDANT_BUSINESS_LOGIC", "REPEATED_DATABASE_QUERIES", "N_PLUS_ONE_QUERY_PATTERN",
    "INEFFICIENT_DATA_PROCESSING", "REPEATED_INTERNAL_API_CALLS", "EXCESSIVE_SERIALIZATION",
    "SLOW_DOWNSTREAM_APPLICATION_DEPENDENCY", "INEFFICIENT_APPLICATION_CACHE", "UNKNOWN_APPLICATION_BOTTLENECK",
]


class FaultDiagnosis(BaseModel):
    """Output contract of the future ML model (interface only)."""
    rule_id: str = "APP-R-056"
    fault_type: str = "API_RESPONSE_TIME_DEGRADATION"
    endpoint: Optional[str] = None
    probable_cause: ProbableCause
    suspected_operation: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: dict = {}
    recommended_action: str  # an ACTION-056-xx id from action_registry.ACTIONS
    requires_approval: bool = False


class FaultIdentifier(Protocol):
    async def identify(self, ml_input: dict) -> FaultDiagnosis: ...


def build_ml_input(endpoint: str, method: str, baseline: dict, windows: list[dict], evidence: dict,
                   duration_seconds: float) -> dict:
    """Structured features for the future model: latency features + application execution evidence."""
    last = windows[-1]
    bd = evidence.get("breakdown_ms", {})
    return {
        "rule_id": "APP-R-056",
        "fault_type": "API_RESPONSE_TIME_DEGRADATION",
        "endpoint": endpoint,
        "http_method": method,
        "latency_features": {
            "historical_average_ms": baseline["baseline_average_ms"],
            "historical_p95_ms": baseline["baseline_p95_ms"],
            "historical_p99_ms": baseline["baseline_p99_ms"],
            "current_average_ms": last["average_latency_ms"],
            "current_p95_ms": last["p95_latency_ms"],
            "current_p99_ms": last["p99_latency_ms"],
            "average_trend_ms": [w["average_latency_ms"] for w in windows],
            "p95_trend_ms": [w["p95_latency_ms"] for w in windows],
            "p99_trend_ms": [w["p99_latency_ms"] for w in windows],
            "degradation_duration_seconds": round(duration_seconds, 1),
            "consecutive_degraded_windows": len(windows),
        },
        "execution_evidence": {
            "trace_ids": evidence.get("trace_ids", []),
            "log_request_ids": evidence.get("request_ids", []),
            "span_breakdown_ms": bd,
            "business_logic_ms": bd.get("business", 0),
            "database_duration_ms": evidence.get("db_duration_ms", 0),
            "database_query_count": evidence.get("db_query_count", 0),
            "repeated_identical_queries": evidence.get("repeated_identical_queries", []),
            "serialization_ms": bd.get("serialization", 0),
            "authentication_ms": bd.get("auth", 0),
            "downstream_dependency_ms": bd.get("dependency", 0),
            "data_processing_ms": bd.get("data_processing", 0),
        },
    }


async def extract_general_features(db, since) -> dict:
    """Aggregate selected-rule features from application_events (for future ML consumption)."""
    pipeline = [
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {"_id": {"rule_id": "$rule_id", "event_type": "$event_type", "endpoint": "$endpoint",
                            "error_code": "$error_code", "api_version": "$api_version"},
                    "count": {"$sum": 1}, "first": {"$min": "$timestamp"}, "last": {"$max": "$timestamp"}}},
    ]
    cur = await db.application_events.aggregate(pipeline)
    rows = await cur.to_list(None)
    return {
        "since": since,
        "groups": [{**r["_id"], "count": r["count"], "first": r["first"], "last": r["last"]} for r in rows],
    }
