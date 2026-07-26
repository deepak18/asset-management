"""Read-through market-data cache — Postgres first, network last (PLAN.md §1.3).

Free data providers (AlphaVantage free tier) are heavily rate-limited, so the
cache is **mandatory**, not an optimization: reads are served from Postgres, and
the upstream is only called on a miss or when a cached entry has aged past its
TTL. If the upstream then fails, we fall back to the *stale* cached value so the
app stays usable when quota is exhausted.

Every ``get_or_fetch`` returns a :class:`CacheOutcome` whose ``status`` makes the
provenance of the answer explicit — was it fresh cache, a fresh network refresh,
or a stale fallback? The UI/AI layer can surface that honestly (§7).

Design notes
------------
* **Generic over the schema.** The caller passes the Pydantic ``schema`` to
  (de)serialize, so this one method caches ``Quote``, ``CompanyProfile``, or a
  ``FinancialStatements`` set identically — strong typing is preserved at the
  edges even though the stored ``payload`` is opaque JSON.
* **Injectable clock.** ``now`` is injected so tests drive TTL expiry
  deterministically without sleeping.
* **UTC-normalized timestamps.** We always store UTC. SQLite drops ``tzinfo`` on
  read, so ``_ensure_aware`` re-stamps naive values as UTC before any arithmetic;
  on Postgres (tz-aware) it is a no-op. This keeps freshness math dialect-safe.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketdata.errors import MarketDataUnavailableError
from app.marketdata.models import MarketDataCacheEntry
from app.marketdata.schemas import MarketDataType


class CacheStatus(StrEnum):
    """Provenance of a cache answer."""

    HIT = "HIT"            # served fresh from cache; upstream not called
    REFRESHED = "REFRESHED"  # miss/expiry → fetched upstream and stored
    STALE = "STALE"        # upstream failed → served an expired cached value


@dataclass(frozen=True)
class CacheOutcome[CacheableT: BaseModel]:
    """A cached/fetched value plus how we obtained it and when it was stored."""

    value: CacheableT
    status: CacheStatus
    fetched_at: datetime


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ensure_aware(dt: datetime) -> datetime:
    """Treat a naive datetime as UTC (we only ever store UTC)."""

    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class ReadThroughCache:
    """Serve typed market data from Postgres, hitting the network only when needed."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        ttl_seconds: float,
        provider_code: str,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._session = session
        self._ttl = timedelta(seconds=ttl_seconds)
        self._provider_code = provider_code
        self._now = now

    async def get_or_fetch[CacheableT: BaseModel](
        self,
        *,
        data_type: MarketDataType,
        symbol: str,
        schema: type[CacheableT],
        fetch: Callable[[], Awaitable[CacheableT]],
        as_of: Callable[[CacheableT], datetime] | None = None,
    ) -> CacheOutcome[CacheableT]:
        """Return a fresh cached value, else fetch upstream, else fall back to stale.

        ``fetch`` is the upstream call (mocked in unit tests). It must raise
        :class:`MarketDataUnavailableError` on failure so we can decide whether a
        stale cached value can stand in. ``as_of`` optionally extracts the datum's
        own source timestamp for provenance; when omitted we stamp "now".
        """

        now = self._now()
        entry = await self._read(data_type, symbol)

        if entry is not None and self._is_fresh(entry, now):
            value = schema.model_validate_json(entry.payload)
            return CacheOutcome(value, CacheStatus.HIT, _ensure_aware(entry.fetched_at))

        try:
            fetched = await fetch()
        except MarketDataUnavailableError:
            if entry is not None:
                stale = schema.model_validate_json(entry.payload)
                return CacheOutcome(stale, CacheStatus.STALE, _ensure_aware(entry.fetched_at))
            raise

        stamped = as_of(fetched) if as_of is not None else now
        await self._write(data_type, symbol, fetched, as_of=stamped, fetched_at=now)
        return CacheOutcome(fetched, CacheStatus.REFRESHED, now)

    def _is_fresh(self, entry: MarketDataCacheEntry, now: datetime) -> bool:
        return now - _ensure_aware(entry.fetched_at) <= self._ttl

    async def _read(
        self, data_type: MarketDataType, symbol: str
    ) -> MarketDataCacheEntry | None:
        stmt = select(MarketDataCacheEntry).where(
            MarketDataCacheEntry.provider_code == self._provider_code,
            MarketDataCacheEntry.data_type == data_type.value,
            MarketDataCacheEntry.symbol == symbol,
        )
        return (await self._session.scalars(stmt)).first()

    async def _write(
        self,
        data_type: MarketDataType,
        symbol: str,
        value: BaseModel,
        *,
        as_of: datetime,
        fetched_at: datetime,
    ) -> None:
        payload = value.model_dump_json()
        entry = await self._read(data_type, symbol)
        if entry is None:
            self._session.add(
                MarketDataCacheEntry(
                    provider_code=self._provider_code,
                    data_type=data_type.value,
                    symbol=symbol,
                    payload=payload,
                    as_of=as_of,
                    fetched_at=fetched_at,
                )
            )
        else:
            entry.payload = payload
            entry.as_of = as_of
            entry.fetched_at = fetched_at
        await self._session.commit()




