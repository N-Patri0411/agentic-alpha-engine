"""Small injectable request pacer used by public-data adapters."""

from __future__ import annotations

import time
from collections.abc import Callable


class RequestPacer:
    """Enforce a minimum interval without hiding retries or failed requests."""

    def __init__(
        self,
        minimum_interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds must be non-negative")
        self._minimum_interval_seconds = minimum_interval_seconds
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: float | None = None

    def wait(self) -> None:
        """Wait before a request when the prior request was too recent."""

        now = self._clock()
        if self._last_request_at is not None:
            remaining = self._minimum_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                self._sleeper(remaining)
        self._last_request_at = self._clock()
