import json
import os


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _json(name: str, default: dict) -> dict:
    raw = os.getenv(name)
    return json.loads(raw) if raw else default


DEFAULT_JWT_SECRET = "dev-only-change-me-please-0123456789abcdef"


class Settings:
    """Plain mutable settings object (tests override attributes directly)."""

    def __init__(self) -> None:
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.mongo_uri = os.getenv("MONGO_URI", "mongodb://database:27017/?replicaSet=rs0")
        self.db_name = os.getenv("MONGO_DB_NAME", "minishop")
        self.jwt_secret = os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
        self.jwt_expire_minutes = _int("JWT_EXPIRE_MINUTES", 480)
        self.bcrypt_rounds = _int("BCRYPT_ROUNDS", 12)
        self.cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

        # Development-only scenario / fault-injection endpoints. Never on in production.
        self._enable_dev = _bool("ENABLE_DEV_SCENARIOS", False)

        # API version compatibility (APP-R-002)
        self.min_client_version = os.getenv("MIN_CLIENT_VERSION", "1.0.0")
        self.legacy_adapter_min_version = os.getenv("LEGACY_ADAPTER_MIN_VERSION", "0.9.0")

        # Retry (APP-R-030)
        self.retry_max_attempts = _int("RETRY_MAX_ATTEMPTS", 3)
        self.retry_base_delay_s = _float("RETRY_BASE_DELAY_S", 0.05)
        self.retry_max_delay_s = _float("RETRY_MAX_DELAY_S", 0.5)
        self.retry_total_budget_s = _float("RETRY_TOTAL_BUDGET_S", 2.0)

        # Optimistic locking (APP-R-040)
        self.optimistic_retry_attempts = _int("OPTIMISTIC_RETRY_ATTEMPTS", 3)

        # ---- APP-R-056 monitoring ----
        self.monitor_enabled = _bool("MONITOR_ENABLED", True)
        self.window_seconds = _int("MONITOR_WINDOW_SECONDS", 60)
        self.max_accumulation_windows = _int("MAX_ACCUMULATION_WINDOWS", 5)
        self.min_samples_window = _int("MIN_SAMPLES_WINDOW", 10)   # below: INSUFFICIENT_DATA
        self.min_samples_p95 = _int("MIN_SAMPLES_P95", 20)
        self.min_samples_p99 = _int("MIN_SAMPLES_P99", 30)
        self.avg_factor = _float("AVG_FACTOR", 2.0)
        self.p95_factor = _float("P95_FACTOR", 2.0)
        self.p99_factor = _float("P99_FACTOR", 3.0)
        self.consecutive_windows = _int("CONSECUTIVE_WINDOWS", 3)
        self.healthy_factor = _float("HEALTHY_FACTOR", 1.25)        # baseline may only learn from windows within this
        self.baseline_min_observations = _int("BASELINE_MIN_OBSERVATIONS", 60)
        self.baseline_max_weight = _int("BASELINE_MAX_WEIGHT", 5000)
        self.max_error_rate_for_baseline = _float("MAX_ERROR_RATE_FOR_BASELINE", 0.05)
        self.verification_windows = _int("VERIFICATION_WINDOWS", 3)
        self.max_verification_windows = _int("MAX_VERIFICATION_WINDOWS", 6)
        self.recovery_factor = _float("RECOVERY_FACTOR", 1.25)
        self.max_action_attempts = _int("MAX_ACTION_ATTEMPTS", 2)
        self.absolute_limits_ms = _json("ABSOLUTE_LIMITS_JSON", {
            "GET /api/v1/products/{product_id}": 3000,
            "GET /api/v1/products": 3000,
            "POST /api/v1/orders": 5000,
        })
        self.endpoint_overrides = _json("ENDPOINT_THRESHOLDS_JSON", {})

        # Tracing
        self.trace_sample_rate = _float("TRACE_SAMPLE_RATE", 0.2)
        self.trace_slow_ms = _float("TRACE_SLOW_MS", 400)
        self.trace_ttl_hours = _int("TRACE_TTL_HOURS", 24)              # ordinary sampled traces
        self.trace_keep_ttl_days = _int("TRACE_KEEP_TTL_DAYS", 7)       # slow / error traces
        self.sample_ttl_hours = _int("LATENCY_SAMPLE_TTL_HOURS", 48)

        if self.environment == "production" and self.jwt_secret == DEFAULT_JWT_SECRET:
            raise RuntimeError("JWT_SECRET must be set when ENVIRONMENT=production")

    @property
    def dev_enabled(self) -> bool:
        return self._enable_dev and self.environment != "production"

    @dev_enabled.setter
    def dev_enabled(self, value: bool) -> None:
        self._enable_dev = value


settings = Settings()
