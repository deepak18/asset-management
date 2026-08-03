"""Tests for the write half of the SQLAlchemy portfolio provider.

Still offline unit tests (in-memory SQLite): they verify the write translation
boundary — typed inputs in, persisted rows out — and that reads see the writes.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio.schemas import PortfolioCreate, Transaction, TransactionType
from app.providers.portfolio_provider import SqlAlchemyPortfolioProvider


async def test_create_portfolio_assigns_id(async_session: AsyncSession) -> None:
    provider = SqlAlchemyPortfolioProvider(async_session)

    summary = await provider.create_portfolio(
        PortfolioCreate(name="Retirement", base_currency="usd")
    )
    assert summary.id > 0
    assert summary.name == "Retirement"
    assert summary.base_currency == "USD"  # normalized on write

    # Round-trip: a fresh read sees it.
    again = await provider.get_portfolio(summary.id)
    assert again is not None
    assert again.name == "Retirement"


async def test_list_portfolios_returns_all_created(async_session: AsyncSession) -> None:
    provider = SqlAlchemyPortfolioProvider(async_session)
    assert await provider.list_portfolios() == []

    await provider.create_portfolio(PortfolioCreate(name="Taxable", base_currency="USD"))
    await provider.create_portfolio(PortfolioCreate(name="Roth", base_currency="USD"))

    rows = await provider.list_portfolios()
    assert [p.name for p in rows] == ["Taxable", "Roth"]  # ordered by id


async def test_add_transactions_persists_and_counts(async_session: AsyncSession) -> None:
    provider = SqlAlchemyPortfolioProvider(async_session)
    pid = (await provider.create_portfolio(PortfolioCreate(name="M", base_currency="USD"))).id

    count = await provider.add_transactions(
        pid,
        [
            Transaction(
                ticker="AAPL", type=TransactionType.BUY, trade_date=date(2020, 1, 1),
                currency="USD", quantity=Decimal("10"), price=Decimal("100"),
            ),
            Transaction(
                ticker="AAPL", type=TransactionType.SELL, trade_date=date(2021, 1, 1),
                currency="USD", quantity=Decimal("4"), price=Decimal("150"),
            ),
        ],
    )
    assert count == 2

    txns = await provider.list_transactions(pid)
    assert [t.type for t in txns] == [TransactionType.BUY, TransactionType.SELL]
    assert txns[0].price == Decimal("100")  # exact Decimal round-trip


async def test_upsert_holding_is_idempotent_and_preserves(async_session: AsyncSession) -> None:
    provider = SqlAlchemyPortfolioProvider(async_session)
    pid = (await provider.create_portfolio(PortfolioCreate(name="M", base_currency="USD"))).id

    await provider.upsert_holding(pid, "AAPL", sector="Tech", industry="Hardware")
    # Re-upsert with only a ticker must NOT blank out prior classification.
    await provider.upsert_holding(pid, "AAPL")

    holdings = await provider.list_holdings(pid)
    assert len(holdings) == 1
    assert holdings[0].sector == "Tech"
    assert holdings[0].industry == "Hardware"

    # Upserting a real value overwrites.
    await provider.upsert_holding(pid, "AAPL", sector="Technology")
    holdings = await provider.list_holdings(pid)
    assert holdings[0].sector == "Technology"
