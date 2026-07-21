from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

log = logging.getLogger("backend_health.retry")

T = TypeVar("T")


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    label: str = "operation",
) -> T:
    """Call `fn()`, retrying transient failures with exponential backoff.

    Retries `attempts` times total (the first call plus `attempts - 1` retries).
    Delay doubles each retry: base, base*2, base*4, ... The last failure's
    exception is re-raised once attempts are exhausted, so a permanent failure
    (bad credentials, malformed NRQL) still surfaces clearly to the caller
    rather than being swallowed.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, re-raised below
            last_exc = exc
            if attempt == attempts:
                break
            delay = base_delay_seconds * (2 ** (attempt - 1))
            log.warning(
                "%s failed (attempt %d/%d): %s; retrying in %.1fs",
                label,
                attempt,
                attempts,
                exc,
                delay,
            )
            sleep(delay)

    assert last_exc is not None  # loop always runs at least once
    raise last_exc
