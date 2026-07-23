"""Tests for the SQLAlchemy portfolio provider against in-memory SQLite.

These are still *unit* tests (offline, no Postgres) — they verify the translation
boundary: ORM rows in, typed domain objects out, with exact Decimals preserved. The
final test proves the provider's output flows straight into the pure calculators,
which is the whole point of the §2 boundary.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency import FxRateTable
from app.portfolio import models
from app.portfolio.calculators import cost_basis_fifo
from app.portfolio.schemas import TransactionType
from app.providers.portfolio_provider import SqlAlchemyPortfolioProvider


async def _seed_portfolio(session: AsyncSession) -> int:
    portfolio = models.Portfolio(name="Main", base_currency="USD")
    session.add(portfolio)
    await session.flush()  # assigns portfolio.id without committing

    session.add_all(
        [
            models.Holding(portfolio_id=portfolio.id, ticker="AAPL", sector="Tech", industry="Hardware"),
            models.Holding(portfolio_id=portfolio.id, ticker="XOM", sector="Energy"),
            models.Transaction(
                portfolio_id=portfolio.id, ticker="AAPL", type=TransactionType.BUY,
                trade_date=date(2026, 1, 1), currency="USD",
                quantity=Decimal("10"), price=Decimal("100"),
            ),
            models.Transaction(
                portfolio_id=portfolio.id, ticker="AAPL", type=TransactionType.SELL,
                trade_date=date(2026, 3, 1), currency="USD",
                quantity=Decimal("4"), price=Decimal("150"),
            ),
        ]
    )
    await session.commit()
    return portfolio.id


async def test_get_portfolio_returns_summary(async_session: AsyncSession) -> None:
    pid = await _seed_portfolio(async_session)
    provider = SqlAlchemyPortfolioProvider(async_session)

    summary = await provider.get_portfolio(pid)
    assert summary is not None
    assert summary.name == "Main"
    assert summary.base_currency == "USD"


async def test_get_portfolio_missing_returns_none(async_session: AsyncSession) -> None:
    provider = SqlAlchemyPortfolioProvider(async_session)
    assert await provider.get_portfolio(999) is None


async def test_list_holdings_maps_classification(async_session: AsyncSession) -> None:
    pid = await _seed_portfolio(async_session)
    provider = SqlAlchemyPortfolioProvider(async_session)

    holdings = await provider.list_holdings(pid)
    by_ticker = {h.ticker: h for h in holdings}
    assert by_ticker["AAPL"].sector == "Tech"
    assert by_ticker["AAPL"].industry == "Hardware"
    assert by_ticker["XOM"].industry is None


async def test_list_transactions_preserves_exact_decimals(async_session: AsyncSession) -> None:
    pid = await _seed_portfolio(async_session)
    provider = SqlAlchemyPortfolioProvider(async_session)

    txns = await provider.list_transactions(pid)
    assert [t.type for t in txns] == [TransactionType.BUY, TransactionType.SELL]
    # Exactness check: value must round-trip through SQLite without float drift.
    assert txns[0].price == Decimal("100")
    assert txns[0].quantity == Decimal("10")


async def test_provider_output_feeds_calculators(async_session: AsyncSession) -> None:
    # End-to-end wiring: DB -> provider -> pure calculator, no ORM leakage.
    pid = await _seed_portfolio(async_session)
    provider = SqlAlchemyPortfolioProvider(async_session)

    txns = await provider.list_transactions(pid)
    result = cost_basis_fifo(txns, FxRateTable(base_currency="USD"))

    # Bought 10@100, sold 4@150 -> realized 4*(150-100)=200; 6 shares open @100=600.
    assert result.realized_pnl_base == Decimal("200")
    assert result.open_quantity == Decimal("6")
    assert result.open_cost_basis_base == Decimal("600")
