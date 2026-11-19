"""APP-R-030: bounded retry with exponential backoff + full jitter. IDEMPOTENT READS ONLY."""
import asyncio
import random
import time

from pymongo.errors import AutoReconnect, ConnectionFailure

from app.config import settings
from app.observability.error_handlers import AppError
from app.observability.event_logger import log_event


class TransientDependencyError(Exception):
    """A transient failure of an application dependency (real or dev-injected)."""


TRANSIENT_ERRORS = (TransientDependencyError, AutoReconnect, ConnectionFailure, asyncio.TimeoutError)


class RetryBudget:
    """Process-wide token bucket so many failing requests cannot cause a retry storm."""

    def __init__(self, capacity: float = 20, refill_per_s: float = 5) -> None:
        self.capacity = capacity
        self.refill = refill_per_s
        self.tokens = capacity
        self.updated = time.monotonic()

    def try_acquire(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


retry_budget = RetryBudget()


def backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter: uniform(0, min(cap, base * 2^(attempt-1)))."""
    ceiling = min(settings.retry_max_delay_s, settings.retry_base_delay_s * (2 ** (attempt - 1)))
    return random.uniform(0, ceiling)


async def retry_idempotent(fn, *, operation: str):
    """Run an idempotent async read, retrying transient failures within a bounded budget.

    NEVER use for side-effecting operations (checkout, status updates, ...)."""
    max_attempts = settings.retry_max_attempts
    deadline = time.monotonic() + settings.retry_total_budget_s
    attempt = 0
    while True:
        attempt += 1
        try:
            result = await fn()
            if attempt > 1:
                await log_event(
                    "TRANSIENT_DEPENDENCY_RECOVERED", "INFO", rule_id="APP-R-030",
                    context={"operation": operation, "attempts": attempt},
                )
            return result
        except TRANSIENT_ERRORS as exc:
            await log_event(
                "TRANSIENT_DEPENDENCY_FAILURE", "WARNING", rule_id="APP-R-030",
                exception_type=type(exc).__name__,
                context={"operation": operation, "attempt": attempt, "max_attempts": max_attempts},
            )
            out_of_budget = attempt >= max_attempts or time.monotonic() >= deadline
            if out_of_budget or not retry_budget.try_acquire():
                raise AppError(
                    503, "DEPENDENCY_UNAVAILABLE",
                    "A dependency is temporarily unavailable. Please retry shortly.",
                    headers={"Retry-After": "2"},
                ) from exc
            await asyncio.sleep(backoff_delay(attempt))
