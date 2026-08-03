"""Unit tests for the write-side ingest service.

The provider boundary is faked (an in-memory dict), so these tests isolate the
orchestration logic: snapshot-to-opening-lot conversion, holding upsert on every
touched ticker, portfolio-existence 404 signalling, and statement import wiring.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.currency import FxRateTable
from app.portfolio.calculators import cost_basis_fifo
from app.portfolio.ingest import PortfolioIngestService, snapshot_to_opening_buy
from app.portfolio.schemas import (
    HoldingInfo,
    PortfolioCreate,
    PortfolioSummary,
    PositionSnapshot,
    Transaction,
    TransactionType,
)


class _FakeProvider:
    """Structural PortfolioProvider + PortfolioWriter backed by dicts."""

    def __init__(self, existing: dict[int, PortfolioSummary] | None = None) -> None:
        self.portfolios: dict[int, PortfolioSummary] = existing or {}
        self.transactions: dict[int, list[Transaction]] = {}
        self.holdings: dict[tuple[int, str], HoldingInfo] = {}
        self._next_id = 100

    async def get_portfolio(self, portfolio_id: int) -> PortfolioSummary | None:
        return self.portfolios.get(portfolio_id)

    async def list_portfolios(self) -> list[PortfolioSummary]:
        return list(self.portfolios.values())

    async def list_transactions(self, portfolio_id: int) -> list[Transaction]:
        return list(self.transactions.get(portfolio_id, []))

    async def list_holdings(self, portfolio_id: int) -> list[HoldingInfo]:
        return [h for (pid, _), h in self.holdings.items() if pid == portfolio_id]

    async def create_portfolio(self, data: PortfolioCreate) -> PortfolioSummary:
        pid = self._next_id
        self._next_id += 1
        summary = PortfolioSummary(id=pid, name=data.name, base_currency=data.base_currency)
        self.portfolios[pid] = summary
        return summary

    async def add_transactions(self, portfolio_id: int, transactions: object) -> int:
        rows = list(transactions)  # type: ignore[call-overload]
        self.transactions.setdefault(portfolio_id, []).extend(rows)
        return len(rows)

    async def upsert_holding(
        self,
        portfolio_id: int,
        ticker: str,
        sector: str | None = None,
        industry: str | None = None,
    ) -> None:
        self.holdings[(portfolio_id, ticker)] = HoldingInfo(
            ticker=ticker, sector=sector, industry=industry
        )


def test_snapshot_total_cost_basis_derives_price() -> None:
    snap = PositionSnapshot(
        ticker="aapl", quantity=Decimal("10"), currency="USD",
        as_of=date(2020, 1, 1), total_cost_basis=Decimal("1500"),
    )
    buy = snapshot_to_opening_buy(snap)
    assert buy.type is TransactionType.BUY
    assert buy.ticker == "AAPL"
    assert buy.price == Decimal("150")  # 1500 / 10
    assert buy.quantity == Decimal("10")

    # The synthetic lot reproduces the asserted cost basis exactly.
    result = cost_basis_fifo([buy], FxRateTable(base_currency="USD"))
    assert result.open_cost_basis_base == Decimal("1500")
    assert result.open_quantity == Decimal("10")


def test_snapshot_per_share_used_directly() -> None:
    snap = PositionSnapshot(
        ticker="MSFT", quantity=Decimal("3"), currency="USD",
        as_of=date(2019, 5, 5), cost_basis_per_share=Decimal("90"),
    )
    assert snapshot_to_opening_buy(snap).price == Decimal("90")


async def test_add_snapshots_records_lots_and_holdings() -> None:
    provider = _FakeProvider({1: PortfolioSummary(id=1, name="M", base_currency="USD")})
    service = PortfolioIngestService(writer=provider, reader=provider)

    result = await service.add_snapshots(
        1,
        [
            PositionSnapshot(
                ticker="AAPL", quantity=Decimal("10"), currency="USD",
                as_of=date(2020, 1, 1), total_cost_basis=Decimal("1000"),
                sector="Tech", industry="Hardware",
            )
        ],
    )
    assert result is not None
    assert result.created_transactions == 1
    assert result.tickers == ("AAPL",)
    # Holding was upserted with the snapshot's classification.
    assert provider.holdings[(1, "AAPL")].sector == "Tech"


async def test_write_to_missing_portfolio_returns_none() -> None:
    provider = _FakeProvider()  # no portfolios
    service = PortfolioIngestService(writer=provider, reader=provider)

    assert await service.add_snapshots(999, []) is None
    assert await service.add_transactions(999, []) is None
