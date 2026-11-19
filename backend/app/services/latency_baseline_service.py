"""Latency statistics and historical baselines (APP-R-056).

Baseline rules:
* Per endpoint + HTTP method (route templates, never individual ids).
* Only HEALTHY windows may update a baseline (see performance_service.evaluate_window): windows that
  are degraded, suspect (>healthy_factor x baseline), low-volume, error-heavy, or recorded while an
  incident is open never contribute -> an incident cannot raise its own baseline.
* Updates are sample-weighted averages with a capped weight, so the baseline stays adaptive.
"""
import math

from app.config import settings
from app.utils.serialization import new_id, utcnow


def percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile on an ascending list."""
    n = len(sorted_values)
    k = max(math.ceil(p / 100 * n) - 1, 0)
    return sorted_values[min(k, n - 1)]


def summarize(durations: list[float]) -> dict:
    v = sorted(durations)
    return {
        "count": len(v),
        "avg": round(sum(v) / len(v), 3),
        "p95": round(percentile(v, 95), 3),
        "p99": round(percentile(v, 99), 3),
        "min": round(v[0], 3),
        "max": round(v[-1], 3),
    }


def thresholds_for(endpoint_key: str) -> dict:
    """Defaults from settings, overridable per endpoint ("METHOD /route/template")."""
    th = {
        "avg_factor": settings.avg_factor,
        "p95_factor": settings.p95_factor,
        "p99_factor": settings.p99_factor,
        "consecutive_windows": settings.consecutive_windows,
        "healthy_factor": settings.healthy_factor,
        "absolute_limit_ms": settings.absolute_limits_ms.get(endpoint_key),
    }
    th.update(settings.endpoint_overrides.get(endpoint_key, {}))
    return th


async def get_baseline(db, endpoint: str, method: str) -> dict | None:
    return await db.api_latency_baselines.find_one({"endpoint": endpoint, "http_method": method})


async def update_baseline(db, endpoint: str, method: str, summary: dict, window_start, window_end) -> dict:
    now = utcnow()
    n = summary["count"]
    existing = await get_baseline(db, endpoint, method)
    if existing is None:
        doc = {
            "_id": new_id("bl"), "endpoint": endpoint, "http_method": method,
            "baseline_average_ms": summary["avg"], "baseline_p95_ms": summary["p95"],
            "baseline_p99_ms": summary["p99"], "observation_count": n,
            "calculation_period": {"from": window_start, "to": window_end},
            "last_updated": now, "baseline_version": 1,
            "status": "ACTIVE" if n >= settings.baseline_min_observations else "LEARNING",
        }
        await db.api_latency_baselines.insert_one(doc)
        return doc

    w_old = min(existing["observation_count"], settings.baseline_max_weight)

    def mix(old: float, new: float) -> float:
        return round((old * w_old + new * n) / (w_old + n), 3)

    obs = existing["observation_count"] + n
    update = {
        "baseline_average_ms": mix(existing["baseline_average_ms"], summary["avg"]),
        "baseline_p95_ms": mix(existing["baseline_p95_ms"], summary["p95"]) if n >= settings.min_samples_p95
        else existing["baseline_p95_ms"],
        "baseline_p99_ms": mix(existing["baseline_p99_ms"], summary["p99"]) if n >= settings.min_samples_p99
        else existing["baseline_p99_ms"],
        "observation_count": obs,
        "calculation_period.to": window_end,
        "last_updated": now,
        "baseline_version": existing["baseline_version"] + 1,
        "status": "ACTIVE" if obs >= settings.baseline_min_observations else "LEARNING",
    }
    await db.api_latency_baselines.update_one({"_id": existing["_id"]}, {"$set": update})
    return await db.api_latency_baselines.find_one({"_id": existing["_id"]})
