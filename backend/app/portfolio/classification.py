"""Holding classification — filling in sector/industry for allocation roll-ups.

Why this exists: a broker activity export contains no classification data. It
tells you that you bought ``NFLX``, not that Netflix is a communication-services
company. So every holding created by an import starts with ``sector = NULL``, and
the allocation calculator honestly buckets it under ``UNCLASSIFIED``. This service
is the backfill that turns those buckets into a real breakdown.

It coordinates only. The descriptive data comes from a
:class:`~app.providers.marketdata_provider.MarketDataProvider` (cache-first, so
repeat calls don't burn free-tier quota), and persistence goes through
:class:`~app.providers.base.PortfolioWriter`. No HTTP, no MCP, and no SQL is
written here, which is what lets the whole thing be tested with two small fakes.

Two deliberate design choices are worth calling out:

*User edits win.* By default we skip MANUAL holdings, even when both fields have
been explicitly cleared, and skip already-classified provider holdings. A vendor
taxonomy is a convenience, not an authority — if you have hand-labelled a holding,
a later backfill must not silently relabel it. ``refresh=True`` opts into
re-fetching everything when you *do* want the vendor's answer.

*Bounded work per request.* Classification is one upstream call per unclassified
ticker, and free-tier providers are slow and quota-limited. Rather than let a
large portfolio hang an HTTP request (or silently blow the daily quota), each call
processes at most ``limit`` tickers and reports how many are ``remaining``. The
caller passes ``next_cursor`` as ``after_ticker`` until ``remaining`` is zero.
Failures advance the cursor too; starting a new sweep retries them. This stays synchronous
and simple; if portfolios ever grow large enough for this to chafe, it can move
behind the same background-job machinery the statement importer already uses,
without changing this service's logic.
"""

from __future__ import annotations

from app.marketdata.errors import MarketDataError
from app.portfolio.schemas import (
    ClassificationFailure,
    ClassificationFailureReason,
    ClassificationSource,
    HoldingClassificationResult,
    HoldingInfo,
)
from app.providers.base import PortfolioProvider, PortfolioWriter
from app.providers.marketdata_provider import MarketDataProvider

# A conservative default: enough to finish a typical retail portfolio in one
# call, small enough that a cold cache cannot stall the request indefinitely.
DEFAULT_CLASSIFY_LIMIT = 25


class HoldingClassificationService:
    """Backfill and manually override holdings' sector/industry metadata."""

    def __init__(
        self,
        reader: PortfolioProvider,
        writer: PortfolioWriter,
        market_data: MarketDataProvider,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._market_data = market_data

    async def classify(
        self,
        portfolio_id: int,
        *,
        refresh: bool = False,
        limit: int = DEFAULT_CLASSIFY_LIMIT,
        after_ticker: str | None = None,
    ) -> HoldingClassificationResult | None:
        """Fetch company profiles for unclassified holdings and persist the result.

        Returns ``None`` when the portfolio does not exist. With ``refresh=True``
        every holding is re-fetched, replacing existing classification with the
        provider's current answer, including clearing fields absent in a usable
        profile. Failed or empty lookups preserve the existing classification.
        """

        if limit < 1:
            raise ValueError("limit must be positive")

        if await self._reader.get_portfolio(portfolio_id) is None:
            return None

        holdings = await self._reader.list_holdings(portfolio_id)

        classified: list[HoldingInfo] = []
        unresolved: list[str] = []
        skipped: list[str] = []
        pending: list[HoldingInfo] = []
        failures: list[ClassificationFailure] = []

        for holding in holdings:
            if after_ticker is not None and holding.ticker <= after_ticker.upper():
                continue
            already = (
                holding.classification_source == ClassificationSource.MANUAL
                or holding.sector is not None
                or holding.industry is not None
            )
            if already and not refresh:
                skipped.append(holding.ticker)
            else:
                pending.append(holding)

        pending.sort(key=lambda h: h.ticker)
        remaining = max(0, len(pending) - limit)
        for holding in pending[:limit]:
            try:
                profile = await self._market_data.get_company_profile(holding.ticker)
            except MarketDataError:
                unresolved.append(holding.ticker)
                failures.append(
                    ClassificationFailure(
                        ticker=holding.ticker,
                        reason=ClassificationFailureReason.PROVIDER_UNAVAILABLE,
                    )
                )
                continue
            if profile is None or (profile.sector is None and profile.industry is None):
                # Either the symbol is unknown upstream or the profile carries no
                # taxonomy. Both are "try again later", not a failure worth
                # aborting the whole batch for.
                unresolved.append(holding.ticker)
                failures.append(
                    ClassificationFailure(
                        ticker=holding.ticker, reason=ClassificationFailureReason.NO_PROFILE
                    )
                )
                continue

            await self._writer.upsert_holding(
                portfolio_id,
                holding.ticker,
                sector=profile.sector,
                industry=profile.industry,
                classification_source=ClassificationSource.PROVIDER,
                clear_fields=tuple(
                    name for name in ("sector", "industry") if getattr(profile, name) is None
                ),
            )
            classified.append(
                HoldingInfo(
                    ticker=holding.ticker,
                    # A provider-owned classification must not retain manual
                    # labels absent from the replacement profile.
                    sector=profile.sector,
                    industry=profile.industry,
                    classification_source=ClassificationSource.PROVIDER,
                    data_gaps=holding.data_gaps,
                )
            )

        return HoldingClassificationResult(
            portfolio_id=portfolio_id,
            classified=tuple(classified),
            unresolved=tuple(unresolved),
            skipped=tuple(skipped),
            remaining=remaining,
            next_cursor=pending[min(limit, len(pending)) - 1].ticker if remaining else None,
            failures=tuple(failures),
        )


__all__ = ["DEFAULT_CLASSIFY_LIMIT", "HoldingClassificationService"]
