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
from decimal import Decimal

from app.core.currency import FxRateTable
from app.portfolio.calculators import (
    XirrError,
    cost_basis_fifo,
    transactions_to_cash_flows,
    xirr,
)
from app.portfolio.schemas import CostBasisResult, PortfolioAnalytics, Transaction
from app.providers.base import PortfolioProvider


class PortfolioService:
    """Assemble portfolio analytics from a provider + the pure calculators."""

    def __init__(self, provider: PortfolioProvider, fx: FxRateTable) -> None:
        self._provider = provider
        self._fx = fx

    async def get_analytics(self, portfolio_id: int) -> PortfolioAnalytics | None:
        """Return aggregated analytics, or ``None`` if the portfolio doesn't exist.

        Steps: (1) resolve identity, (2) pull the ledger, (3) run FIFO cost-basis
        per ticker, (4) roll up base-currency totals, (5) compute whole-portfolio
        XIRR from all cash flows — reported as ``None`` when it is undefined.
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

        return PortfolioAnalytics(
            portfolio=summary,
            base_currency=self._fx.base_currency,
            positions=tuple(positions),
            realized_pnl_base=realized,
            dividends_base=dividends,
            fees_base=fees,
            open_cost_basis_base=open_cost,
            money_weighted_return=money_weighted_return,
        )
