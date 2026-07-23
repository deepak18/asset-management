"""SQLAlchemy-backed implementation of :class:`PortfolioProvider`.

The single responsibility here is **translation**: turn ORM rows into the frozen
Pydantic domain objects (``Transaction``, ``HoldingInfo``, ``PortfolioSummary``) that
the calculators consume. No financial math lives in this layer — it only reads and
maps. That keeps the storage concern isolated behind the provider boundary.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio import models
from app.portfolio.schemas import HoldingInfo, PortfolioSummary, Transaction


class SqlAlchemyPortfolioProvider:
    """Reads portfolio data from a relational DB via an injected async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_portfolio(self, portfolio_id: int) -> PortfolioSummary | None:
        row = await self._session.get(models.Portfolio, portfolio_id)
        if row is None:
            return None
        return PortfolioSummary(id=row.id, name=row.name, base_currency=row.base_currency)

    async def list_transactions(self, portfolio_id: int) -> list[Transaction]:
        stmt = (
            select(models.Transaction)
            .where(models.Transaction.portfolio_id == portfolio_id)
            .order_by(models.Transaction.trade_date, models.Transaction.id)
        )
        rows = (await self._session.scalars(stmt)).all()
        return [
            Transaction(
                ticker=row.ticker,
                type=row.type,
                trade_date=row.trade_date,
                currency=row.currency,
                quantity=row.quantity,
                price=row.price,
                fees=row.fees,
                amount=row.amount,
                split_ratio=row.split_ratio,
            )
            for row in rows
        ]

    async def list_holdings(self, portfolio_id: int) -> list[HoldingInfo]:
        stmt = (
            select(models.Holding)
            .where(models.Holding.portfolio_id == portfolio_id)
            .order_by(models.Holding.ticker)
        )
        rows = (await self._session.scalars(stmt)).all()
        return [
            HoldingInfo(ticker=row.ticker, sector=row.sector, industry=row.industry)
            for row in rows
        ]
