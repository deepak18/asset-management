"""Portfolio orchestration — the seam between provider I/O and the pure calculators.

This layer coordinates; it does **not** compute or fetch:

* Storage I/O lives behind the :class:`~app.providers.base.PortfolioProvider` (§2).
* Financial math lives in :mod:`app.portfolio.calculators` (pure, §1).

``PortfolioService`` fetches typed domain objects from the provider, feeds them to
the deterministic calculators, and assembles a single typed
:class:`~app.portfolio.schemas.PortfolioAnalytics`. Because it depends only on the
provider *interface* (structural ``Protocol``), tests inject a trivial fake — no DB
required (AGENTS.md §11).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.core.currency import FxRateTable, MissingFxRateError
from app.marketdata.errors import MarketDataUnavailableError
from app.portfolio.calculators import (
    XirrError,
    allocation_weights,
    cost_basis_fifo,
    transactions_to_cash_flows,
    unrealized_pnl,
    xirr,
)
from app.portfolio.schemas import (
    AllocationWeight,
    CostBasisResult,
    PortfolioAnalytics,
    PositionValue,
    Transaction,
    UnrealizedResult,
)
from app.providers.base import PortfolioProvider
from app.providers.marketdata_provider import MarketDataProvider


@dataclass(frozen=True)
class _MarketValues:
    """The market-value-dependent slice of the analytics (empty when unpriced)."""

    positions_unrealized: tuple[UnrealizedResult, ...] = ()
    market_value_base: Decimal | None = None
    unrealized_pnl_base: Decimal | None = None
    allocation_by_ticker: tuple[AllocationWeight, ...] = ()
    allocation_by_sector: tuple[AllocationWeight, ...] = ()
    allocation_by_industry: tuple[AllocationWeight, ...] = ()
    unpriced_tickers: tuple[str, ...] = ()
    priced_as_of: datetime | None = None


class PortfolioService:
    """Assemble portfolio analytics from a provider + the pure calculators."""

    def __init__(
        self,
        provider: PortfolioProvider,
        fx: FxRateTable,
        market_data: MarketDataProvider | None = None,
    ) -> None:
        self._provider = provider
        self._fx = fx
        # Optional: when absent (or a price is unavailable) the market-value
        # figures are simply omitted — the deterministic cost-basis analytics
        # never depend on the network being up.
        self._market_data = market_data

    async def get_analytics(self, portfolio_id: int) -> PortfolioAnalytics | None:
        """Return aggregated analytics, or ``None`` if the portfolio doesn't exist.

        Steps: (1) resolve identity, (2) pull the ledger, (3) run FIFO cost-basis
        per ticker, (4) roll up base-currency totals, (5) compute whole-portfolio
        XIRR from all cash flows, (6) if a market-data provider is available, mark
        open positions to market and compute allocation weights — degrading
        gracefully to "unpriced" when a quote or FX rate is missing.
        """

        summary = await self._provider.get_portfolio(portfolio_id)
        if summary is None:
            return None

        transactions = await self._provider.list_transactions(portfolio_id)

        # Group the flat ledger into per-ticker sub-ledgers; cost_basis_fifo is a
        # single-ticker replay, so grouping is what lets one call cover the book.
        by_ticker: dict[str, list[Transaction]] = defaultdict(list)
        for txn in transactions:
            by_ticker[txn.ticker].append(txn)

        # sorted() keeps position order deterministic (stable API responses/tests).
        positions: list[CostBasisResult] = [
            cost_basis_fifo(by_ticker[ticker], self._fx) for ticker in sorted(by_ticker)
        ]

        realized = sum((p.realized_pnl_base for p in positions), Decimal(0))
        dividends = sum((p.dividends_base for p in positions), Decimal(0))
        fees = sum((p.fees_base for p in positions), Decimal(0))
        open_cost = sum((p.open_cost_basis_base for p in positions), Decimal(0))

        # XIRR can be genuinely undefined (empty ledger, single-sign flows). We
        # translate that into an explicit None rather than a misleading number.
        money_weighted_return: Decimal | None
        try:
            rate = xirr(transactions_to_cash_flows(transactions), self._fx)
            money_weighted_return = Decimal(str(rate))
        except XirrError:
            money_weighted_return = None

        market = await self._compute_market_values(portfolio_id, positions)

        return PortfolioAnalytics(
            portfolio=summary,
            base_currency=self._fx.base_currency,
            positions=tuple(positions),
            realized_pnl_base=realized,
            dividends_base=dividends,
            fees_base=fees,
            open_cost_basis_base=open_cost,
            money_weighted_return=money_weighted_return,
            positions_unrealized=market.positions_unrealized,
            market_value_base=market.market_value_base,
            unrealized_pnl_base=market.unrealized_pnl_base,
            allocation_by_ticker=market.allocation_by_ticker,
            allocation_by_sector=market.allocation_by_sector,
            allocation_by_industry=market.allocation_by_industry,
            unpriced_tickers=market.unpriced_tickers,
            priced_as_of=market.priced_as_of,
        )

    async def _compute_market_values(
        self, portfolio_id: int, positions: list[CostBasisResult]
    ) -> _MarketValues:
        """Mark open positions to market and build allocation weights.

        Returns an empty :class:`_MarketValues` when no provider is configured or
        nothing can be priced, so analytics stays useful offline.
        """

        if self._market_data is None:
            return _MarketValues()

        holdings = await self._provider.list_holdings(portfolio_id)
        meta = {h.ticker: h for h in holdings}
        as_of_date = date.today()

        unrealized: list[UnrealizedResult] = []
        values: list[PositionValue] = []
        unpriced: list[str] = []
        priced_as_of: datetime | None = None

        for pos in positions:
            if pos.open_quantity <= 0:  # fully closed → nothing to mark to market
                continue
            try:
                quote = await self._market_data.get_quote(pos.ticker)
            except MarketDataUnavailableError:
                quote = None
            if quote is None:
                unpriced.append(pos.ticker)
                continue
            try:
                marked = unrealized_pnl(
                    pos, quote.price, quote.currency, as_of_date, self._fx
                )
            except MissingFxRateError:
                unpriced.append(pos.ticker)
                continue

            unrealized.append(marked)
            info = meta.get(pos.ticker)
            values.append(
                PositionValue(
                    ticker=pos.ticker,
                    market_value=marked.market_value_base,
                    sector=info.sector if info else None,
                    industry=info.industry if info else None,
                )
            )
            stamped = quote.provenance.as_of
            if priced_as_of is None or stamped > priced_as_of:
                priced_as_of = stamped

        if not unrealized:
            # Nothing priced: still surface which tickers we could not value.
            return _MarketValues(unpriced_tickers=tuple(unpriced))

        return _MarketValues(
            positions_unrealized=tuple(unrealized),
            market_value_base=sum((u.market_value_base for u in unrealized), Decimal(0)),
            unrealized_pnl_base=sum((u.unrealized_pnl_base for u in unrealized), Decimal(0)),
            allocation_by_ticker=tuple(allocation_weights(values, "ticker")),
            allocation_by_sector=tuple(allocation_weights(values, "sector")),
            allocation_by_industry=tuple(allocation_weights(values, "industry")),
            unpriced_tickers=tuple(unpriced),
            priced_as_of=priced_as_of,
        )
