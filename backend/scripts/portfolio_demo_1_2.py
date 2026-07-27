"""Runnable demo of the current system — DB -> provider -> pure calculators.

There is no HTTP API yet, so this script is the fastest way to *see* the deterministic
core working end to end. It:

  1. spins up a throwaway in-memory async SQLite database (no infra needed),
  2. seeds a sample portfolio ledger (buys, a sell, a dividend, two tickers),
  3. reads it back through the SAME provider the API will use later, and
  4. runs the pure calculators (allocation, FIFO cost-basis, unrealized P&L, XIRR)
     and prints a plain-text portfolio report.

Run it (from backend/, venv active):

    uv run python scripts/portfolio_demo_1_2.py

Nothing here contains business logic — it only orchestrates already-tested pieces,
which is exactly how the future service/API layer will use them.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.currency import FxRateTable
from app.core.database import Base
from app.portfolio import models
from app.portfolio.calculators import (
    allocation_weights,
    cost_basis_fifo,
    transactions_to_cash_flows,
    unrealized_pnl,
    xirr,
)
from app.portfolio.schemas import CashFlow, PositionValue, TransactionType
from app.providers.portfolio_provider import SqlAlchemyPortfolioProvider

# "Today" for valuing open positions and annualizing XIRR.
VALUATION_DATE = date(2026, 7, 23)

# Latest prices (native currency == USD here). Injected, never fetched — the
# market-data provider will supply these in a later phase.
CURRENT_PRICES: dict[str, Decimal] = {"AAPL": Decimal("210"), "MSFT": Decimal("330")}


async def seed(session: AsyncSession) -> int:
    """Insert a sample portfolio and return its id."""

    portfolio = models.Portfolio(name="Growth", base_currency="USD")
    session.add(portfolio)
    await session.flush()

    session.add_all(
        [
            models.Holding(portfolio_id=portfolio.id, ticker="AAPL", sector="Tech", industry="Hardware"),
            models.Holding(portfolio_id=portfolio.id, ticker="MSFT", sector="Tech", industry="Software"),
            # AAPL: two buys, a partial sell, and a dividend.
            models.Transaction(portfolio_id=portfolio.id, ticker="AAPL", type=TransactionType.BUY,
                               trade_date=date(2025, 1, 15), currency="USD", quantity=Decimal("10"), price=Decimal("150")),
            models.Transaction(portfolio_id=portfolio.id, ticker="AAPL", type=TransactionType.BUY,
                               trade_date=date(2025, 6, 10), currency="USD", quantity=Decimal("5"), price=Decimal("170")),
            models.Transaction(portfolio_id=portfolio.id, ticker="AAPL", type=TransactionType.DIVIDEND,
                               trade_date=date(2025, 9, 1), currency="USD", amount=Decimal("12")),
            models.Transaction(portfolio_id=portfolio.id, ticker="AAPL", type=TransactionType.SELL,
                               trade_date=date(2026, 1, 20), currency="USD", quantity=Decimal("4"), price=Decimal("200")),
            # MSFT: a single buy, still fully open.
            models.Transaction(portfolio_id=portfolio.id, ticker="MSFT", type=TransactionType.BUY,
                               trade_date=date(2025, 3, 1), currency="USD", quantity=Decimal("8"), price=Decimal("300")),
        ]
    )
    await session.commit()
    return portfolio.id


async def main() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        portfolio_id = await seed(session)
        provider = SqlAlchemyPortfolioProvider(session)

        summary = await provider.get_portfolio(portfolio_id)
        holdings = await provider.list_holdings(portfolio_id)
        all_txns = await provider.list_transactions(portfolio_id)

    await engine.dispose()

    assert summary is not None
    fx = FxRateTable(base_currency=summary.base_currency)  # USD-only for this demo
    tickers = sorted({t.ticker for t in all_txns})

    print(f"\n=== Portfolio: {summary.name} (base {summary.base_currency}) ===\n")

    position_values: list[PositionValue] = []
    portfolio_flows: list[CashFlow] = []
    total_realized = Decimal(0)
    total_unrealized = Decimal(0)
    total_dividends = Decimal(0)

    holding_meta = {h.ticker: h for h in holdings}

    for ticker in tickers:
        txns = [t for t in all_txns if t.ticker == ticker]
        cb = cost_basis_fifo(txns, fx)
        price = CURRENT_PRICES[ticker]
        un = unrealized_pnl(cb, price, summary.base_currency, VALUATION_DATE, fx)

        total_realized += cb.realized_pnl_base
        total_unrealized += un.unrealized_pnl_base
        total_dividends += cb.dividends_base

        meta = holding_meta[ticker]
        position_values.append(
            PositionValue(ticker=ticker, market_value=un.market_value_base,
                          sector=meta.sector, industry=meta.industry)
        )

        # Per-position cash flows + a terminal mark-to-market inflow for XIRR.
        flows = transactions_to_cash_flows(txns)
        if cb.open_quantity > 0:
            flows.append(CashFlow(date=VALUATION_DATE, amount=un.market_value_base,
                                  currency=summary.base_currency))
        portfolio_flows.extend(flows)

        try:
            pos_xirr = xirr(flows, fx)
            xirr_str = f"{pos_xirr * 100:6.2f}%"
        except Exception:
            xirr_str = "   n/a"

        print(f"  {ticker:5}  open {cb.open_quantity:>4} @ cost {cb.open_cost_basis_base:>9} "
              f"| mkt {un.market_value_base:>9} | realized {cb.realized_pnl_base:>7} "
              f"| unrealized {un.unrealized_pnl_base:>8} | XIRR {xirr_str}")

    print("\n  --- Allocation (by ticker) ---")
    for row in allocation_weights(position_values, group_by="ticker"):
        print(f"    {row.key:5}  {row.weight * 100:6.2f}%   (${row.market_value})")

    print("\n  --- Allocation (by sector) ---")
    for row in allocation_weights(position_values, group_by="sector"):
        print(f"    {row.key:10}  {row.weight * 100:6.2f}%")

    port_xirr = xirr(portfolio_flows, fx)
    print("\n  --- Totals (USD) ---")
    print(f"    realized P&L   : {total_realized}")
    print(f"    unrealized P&L : {total_unrealized}")
    print(f"    dividends      : {total_dividends}")
    print(f"    portfolio XIRR : {port_xirr * 100:.2f}%\n")


if __name__ == "__main__":
    asyncio.run(main())

