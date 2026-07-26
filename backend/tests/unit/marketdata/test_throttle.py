"""Deterministic rate-limiter tests with injected clock + sleep (no real waiting)."""

from __future__ import annotations

from app.marketdata.throttle import AsyncRateLimiter


class _Clock:
    def __init__(self, start: float) -> None:
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        # Simulate the passage of time so the limiter's bookkeeping advances too.
        self.sleeps.append(seconds)
        self.t += seconds


async def test_first_call_does_not_wait() -> None:
    clock = _Clock(100.0)
    limiter = AsyncRateLimiter(10.0, now=clock.now, sleep=clock.sleep)
    await limiter.acquire()
    assert clock.sleeps == []


async def test_second_immediate_call_waits_remaining_interval() -> None:
    clock = _Clock(100.0)
    limiter = AsyncRateLimiter(10.0, now=clock.now, sleep=clock.sleep)
    await limiter.acquire()  # t=100, no wait
    await limiter.acquire()  # t still 100 → must wait the full 10s
    assert clock.sleeps == [10.0]


async def test_call_after_interval_does_not_wait() -> None:
    clock = _Clock(100.0)
    limiter = AsyncRateLimiter(10.0, now=clock.now, sleep=clock.sleep)
    await limiter.acquire()
    clock.t += 25.0  # well past the interval
    await limiter.acquire()
    assert clock.sleeps == []


async def test_zero_interval_never_waits() -> None:
    clock = _Clock(0.0)
    limiter = AsyncRateLimiter(0.0, now=clock.now, sleep=clock.sleep)
    await limiter.acquire()
    await limiter.acquire()
    assert clock.sleeps == []
