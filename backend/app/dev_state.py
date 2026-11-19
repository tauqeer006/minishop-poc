"""Development-only controlled fault state.

Everything here is inert unless settings.dev_enabled is true (ENABLE_DEV_SCENARIOS=true and
ENVIRONMENT != production). It never weakens security or validation; it only lets the scenario
runner (a) switch the product-details handler to a deliberately inefficient variant, (b) add a
simulated per-query latency, (c) inject transient read failures, and (d) inject a failure inside
the checkout transaction.
"""
from app.config import settings


class DevState:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.product_handler = "optimized"   # "optimized" | "inefficient"
        self.repeat = 1                      # repeated identical product queries when inefficient
        self.query_delay_ms = 0.0            # simulated DB round-trip per product lookup
        self.base_delay_ms = 0.0             # simulated non-DB business processing
        self.read_fault_remaining = 0        # transient failures to inject into product reads
        self.checkout_failure = False        # raise inside the checkout transaction after stock update
        self.monitor_paused = False          # pause the periodic window closer (scenario determinism)

    def snapshot(self) -> dict:
        return {
            "enabled": settings.dev_enabled,
            "monitor_paused": self.monitor_paused,
            "product_handler": self.product_handler,
            "repeat": self.repeat,
            "query_delay_ms": self.query_delay_ms,
            "base_delay_ms": self.base_delay_ms,
            "read_fault_remaining": self.read_fault_remaining,
            "checkout_failure": self.checkout_failure,
        }


state = DevState()


def active() -> bool:
    return settings.dev_enabled


def consume_read_fault() -> bool:
    if active() and state.read_fault_remaining > 0:
        state.read_fault_remaining -= 1
        return True
    return False
