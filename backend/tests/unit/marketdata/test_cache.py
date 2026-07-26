"""Read-through cache behaviour: hit / miss-refresh / TTL-expiry / stale-fallback.

The upstream fetch is a fake in-process coroutine — no network — and the clock is
injected so TTL expiry is deterministic (no sleeping).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketdata.cache import CacheStatus, ReadThroughCache
from app.marketdata.errors import MarketDataUnavailableError
from app.marketdata.schemas import MarketDataProvenance, MarketDataType, Quote

_T0 = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def _quote(price: str) -> Quote:
    return Quote(
        ticker="AAPL",
        price=Decimal(price),
        currency="USD",
        provenance=MarketDataProvenance(
            provider_code="ALPHAVANTAGE", source_table="GLOBAL_QUOTE", as_of=_T0
        ),
    )


class _Clock:
    """A tiny movable clock for deterministic TTL tests."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _counting_fetch(quote: Quote, calls: list[int]) -> Callable[[], Awaitable[Quote]]:
    async def fetch() -> Quote:
        calls.append(1)
        return quote

    return fetch


def _make_cache(session: AsyncSession, clock: _Clock, ttl: float = 3600) -> ReadThroughCache:
    return ReadThroughCache(
        session, ttl_seconds=ttl, provider_code="ALPHAVANTAGE", now=clock
    )


async def test_miss_fetches_upstream_and_stores(async_session: AsyncSession) -> None:
    clock = _Clock(_T0)
    calls: list[int] = []
    cache = _make_cache(async_session, clock)

    outcome = await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE,
        symbol="AAPL",
        schema=Quote,
        fetch=_counting_fetch(_quote("190.55"), calls),
    )

    assert outcome.status is CacheStatus.REFRESHED
    assert outcome.value.price == Decimal("190.55")
    assert len(calls) == 1


async def test_fresh_hit_does_not_call_upstream(async_session: AsyncSession) -> None:
    clock = _Clock(_T0)
    calls: list[int] = []
    cache = _make_cache(async_session, clock)

    await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE, symbol="AAPL", schema=Quote,
        fetch=_counting_fetch(_quote("190.55"), calls),
    )
    # Second read, still within TTL → served from cache, upstream untouched.
    outcome = await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE, symbol="AAPL", schema=Quote,
        fetch=_counting_fetch(_quote("999.99"), calls),
    )

    assert outcome.status is CacheStatus.HIT
    assert outcome.value.price == Decimal("190.55")
    assert len(calls) == 1  # not called again


async def test_expired_entry_refetches(async_session: AsyncSession) -> None:
    clock = _Clock(_T0)
    calls: list[int] = []
    cache = _make_cache(async_session, clock, ttl=60)

    await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE, symbol="AAPL", schema=Quote,
        fetch=_counting_fetch(_quote("190.55"), calls),
    )
    clock.advance(120)  # past the 60s TTL
    outcome = await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE, symbol="AAPL", schema=Quote,
        fetch=_counting_fetch(_quote("201.10"), calls),
    )

    assert outcome.status is CacheStatus.REFRESHED
    assert outcome.value.price == Decimal("201.10")
    assert len(calls) == 2


async def test_stale_fallback_when_upstream_fails(async_session: AsyncSession) -> None:
    clock = _Clock(_T0)
    calls: list[int] = []
    cache = _make_cache(async_session, clock, ttl=60)

    await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE, symbol="AAPL", schema=Quote,
        fetch=_counting_fetch(_quote("190.55"), calls),
    )
    clock.advance(120)  # expire it

    async def failing_fetch() -> Quote:
        raise MarketDataUnavailableError("rate limit exhausted")

    outcome = await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE, symbol="AAPL", schema=Quote, fetch=failing_fetch
    )

    # Quota is spent, but we still serve the last-known value, flagged STALE.
    assert outcome.status is CacheStatus.STALE
    assert outcome.value.price == Decimal("190.55")


async def test_miss_with_upstream_failure_raises(async_session: AsyncSession) -> None:
    clock = _Clock(_T0)
    cache = _make_cache(async_session, clock)

    async def failing_fetch() -> Quote:
        raise MarketDataUnavailableError("network down")

    # No cached value to fall back to → the error must surface.
    with pytest.raises(MarketDataUnavailableError):
        await cache.get_or_fetch(
            data_type=MarketDataType.QUOTE, symbol="AAPL", schema=Quote, fetch=failing_fetch
        )


async def test_payload_preserves_exact_decimal(async_session: AsyncSession) -> None:
    clock = _Clock(_T0)
    calls: list[int] = []
    cache = _make_cache(async_session, clock)

    # Store, then force a fresh HIT to prove the JSON round-trip is exact.
    await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE, symbol="AAPL", schema=Quote,
        fetch=_counting_fetch(_quote("0.012"), calls),
    )
    outcome = await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE, symbol="AAPL", schema=Quote,
        fetch=_counting_fetch(_quote("9.99"), calls),
    )

    assert outcome.status is CacheStatus.HIT
    assert outcome.value.price == Decimal("0.012")  # no float drift through storage


async def test_symbols_are_cached_independently(async_session: AsyncSession) -> None:
    clock = _Clock(_T0)
    calls: list[int] = []
    cache = _make_cache(async_session, clock)

    await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE, symbol="AAPL", schema=Quote,
        fetch=_counting_fetch(_quote("190.55"), calls),
    )
    outcome = await cache.get_or_fetch(
        data_type=MarketDataType.QUOTE, symbol="MSFT", schema=Quote,
        fetch=_counting_fetch(_quote("410.00"), calls),
    )

    # Different symbol → its own key → a real fetch, not AAPL's cache.
    assert outcome.status is CacheStatus.REFRESHED
    assert outcome.value.price == Decimal("410.00")
    assert len(calls) == 2

