"""A minimal async rate limiter for upstream market-data calls.

Free providers (AlphaVantage free tier) cap requests per minute, so we space out
*upstream* calls. Cache hits never touch this — only real fetches do. The clock and
sleep are injected so the interval logic is unit-tested deterministically without
real waiting, and an ``asyncio.Lock`` serializes concurrent callers.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class AsyncRateLimiter:
    """Enforce a minimum interval between successive ``acquire()`` calls."""

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._min_interval = min_interval_seconds
        self._now = now
        self._sleep = sleep
        self._last: float | None = None
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until at least ``min_interval_seconds`` has passed since the last call."""

        if self._min_interval <= 0:
            return
        async with self._lock:
            if self._last is not None:
                elapsed = self._now() - self._last
                remaining = self._min_interval - elapsed
                if remaining > 0:
                    await self._sleep(remaining)
            self._last = self._now()
