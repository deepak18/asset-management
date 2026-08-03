"""Portfolio write orchestration — manual entry, snapshots, and statement import.

This is the write-side counterpart to :class:`app.portfolio.service.PortfolioService`
(which is read-only analytics). It coordinates; it holds no financial math and does no
storage I/O itself:

* Persistence lives behind :class:`~app.providers.base.PortfolioWriter`.
* Statement decoding lives behind :class:`~app.portfolio.statements.StatementParser`.

The one deliberate modeling choice here is how a *snapshot* becomes ledger data.
A user with a decade-old position doesn't want to re-key every trade, so we let them
assert the position as it stands — quantity + cost basis — and record it as a single
opening ``BUY`` lot. Because the ledger stays the single source of truth, every
downstream calculator (FIFO cost basis, unrealized P&L, allocation) works unchanged;
only the money-weighted return honestly reports "undefined" when the opening date is
a placeholder rather than a real purchase date.
"""

from __future__ import annotations

from datetime import date

from app.portfolio.schemas import (
    LedgerIngestResult,
    PortfolioCreate,
    PortfolioSummary,
    PositionSnapshot,
    Transaction,
    TransactionType,
)
from app.providers.base import PortfolioProvider, PortfolioWriter


def snapshot_to_opening_buy(snapshot: PositionSnapshot) -> Transaction:
    """Convert a current-holding snapshot into one opening ``BUY`` lot.

    The per-share opening price is taken directly when supplied, otherwise derived
    as ``total_cost_basis / quantity`` — so the recorded lot's cost basis reproduces
    exactly what the user asserted. Fees are zero because a snapshot is a stated
    position, not a fresh trade. ``as_of`` falls back to today when unknown.
    """

    if snapshot.cost_basis_per_share is not None:
        price = snapshot.cost_basis_per_share
    else:
        # Validated by the schema: exactly one cost-basis form is present.
        assert snapshot.total_cost_basis is not None
        price = snapshot.total_cost_basis / snapshot.quantity

    return Transaction(
        ticker=snapshot.ticker.upper(),
        type=TransactionType.BUY,
        trade_date=snapshot.as_of or date.today(),
        currency=snapshot.currency.upper(),
        quantity=snapshot.quantity,
        price=price,
        sector=snapshot.sector,
        industry=snapshot.industry,
    )


class PortfolioIngestService:
    """Record manually-entered trades, position snapshots, and imported statements."""

    def __init__(self, writer: PortfolioWriter, reader: PortfolioProvider) -> None:
        # ``reader`` is used purely to confirm a portfolio exists before writing to
        # it (so a bad id yields a clean 404 instead of orphaned rows). A single
        # SQLAlchemy provider instance satisfies both roles.
        self._writer = writer
        self._reader = reader

    async def create_portfolio(self, data: PortfolioCreate) -> PortfolioSummary:
        """Create a new empty portfolio."""

        return await self._writer.create_portfolio(data)

    async def add_transactions(
        self, portfolio_id: int, transactions: list[Transaction]
    ) -> LedgerIngestResult | None:
        """Append raw ledger events (manual entry). ``None`` if the portfolio is absent."""

        return await self._record(portfolio_id, transactions)

    async def add_snapshots(
        self, portfolio_id: int, snapshots: list[PositionSnapshot]
    ) -> LedgerIngestResult | None:
        """Record current-holding snapshots as opening ``BUY`` lots.

        ``None`` if the portfolio does not exist.
        """

        transactions = [snapshot_to_opening_buy(s) for s in snapshots]
        return await self._record(portfolio_id, transactions)


    async def _record(
        self, portfolio_id: int, transactions: list[Transaction]
    ) -> LedgerIngestResult | None:
        """Persist transactions + ensure a holding row exists for each ticker touched."""

        if await self._reader.get_portfolio(portfolio_id) is None:
            return None

        created = await self._writer.add_transactions(portfolio_id, transactions)

        # Ensure every touched ticker is a tracked holding so it appears in the
        # holdings/allocation views, carrying any classification the caller supplied.
        seen: dict[str, tuple[str | None, str | None]] = {}
        for txn in transactions:
            prev = seen.get(txn.ticker, (None, None))
            seen[txn.ticker] = (txn.sector or prev[0], txn.industry or prev[1])
        for ticker, (sector, industry) in seen.items():
            await self._writer.upsert_holding(portfolio_id, ticker, sector, industry)

        return LedgerIngestResult(
            portfolio_id=portfolio_id,
            created_transactions=created,
            tickers=tuple(sorted(seen)),
        )


__all__ = [
    "PortfolioIngestService",
    "snapshot_to_opening_buy",
]
