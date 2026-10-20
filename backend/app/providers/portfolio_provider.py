"""SQLAlchemy-backed implementation of the portfolio provider interfaces.

The single responsibility here is **translation**: turn ORM rows into the frozen
Pydantic domain objects (``Transaction``, ``HoldingInfo``, ``PortfolioSummary``) that
the calculators consume, and turn typed write inputs back into ORM rows. No financial
math lives in this layer — it only reads, maps, and persists. That keeps the storage
concern isolated behind the provider boundary.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio import models
from app.portfolio.schemas import (
    ClassificationSource,
    HoldingInfo,
    PortfolioCreate,
    PortfolioSummary,
    Transaction,
)
from app.providers.statement_import_store import SqlAlchemyStatementImportStore


class SqlAlchemyPortfolioProvider:
    """Reads *and writes* portfolio data via an injected async session.

    Satisfies both ``PortfolioProvider`` (read) and ``PortfolioWriter`` (write)
    structurally — the two Protocols exist to segregate capability at call sites,
    not to force two classes over one table set.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_portfolio(self, portfolio_id: int) -> PortfolioSummary | None:
        row = await self._session.get(models.Portfolio, portfolio_id)
        if row is None:
            return None
        return PortfolioSummary(id=row.id, name=row.name, base_currency=row.base_currency)

    async def list_portfolios(self) -> list[PortfolioSummary]:
        stmt = select(models.Portfolio).order_by(models.Portfolio.id)
        rows = (await self._session.scalars(stmt)).all()
        return [
            PortfolioSummary(id=row.id, name=row.name, base_currency=row.base_currency)
            for row in rows
        ]

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
        issues = await SqlAlchemyStatementImportStore(self._session).list_unresolved(portfolio_id)
        return [
            HoldingInfo(
                ticker=row.ticker,
                sector=row.sector,
                industry=row.industry,
                classification_source=ClassificationSource(row.classification_source),
                data_gaps=tuple(
                    sorted(
                        {
                            gap
                            for item in issues
                            if item.ticker == row.ticker
                            for gap in item.data_gaps
                        }
                    )
                ),
            )
            for row in rows
        ]

    async def get_holding(self, portfolio_id: int, ticker: str) -> HoldingInfo | None:
        stmt = select(models.Holding).where(
            models.Holding.portfolio_id == portfolio_id,
            models.Holding.ticker == ticker.upper(),
        )
        row = (await self._session.scalars(stmt)).first()
        if row is None:
            return None
        issues = await SqlAlchemyStatementImportStore(self._session).list_unresolved(portfolio_id)
        return HoldingInfo(
            ticker=row.ticker,
            sector=row.sector,
            industry=row.industry,
            classification_source=ClassificationSource(row.classification_source),
            data_gaps=tuple(
                sorted(
                    {gap for item in issues if item.ticker == row.ticker for gap in item.data_gaps}
                )
            ),
        )

    # --- writes -----------------------------------------------------------

    async def create_portfolio(self, data: PortfolioCreate) -> PortfolioSummary:
        row = models.Portfolio(name=data.name, base_currency=data.base_currency.upper())
        self._session.add(row)
        await self._session.flush()  # assigns row.id
        await self._session.commit()
        return PortfolioSummary(id=row.id, name=row.name, base_currency=row.base_currency)

    async def add_transactions(self, portfolio_id: int, transactions: Sequence[Transaction]) -> int:
        rows = [
            models.Transaction(
                portfolio_id=portfolio_id,
                ticker=txn.ticker,
                type=txn.type,
                trade_date=txn.trade_date,
                currency=txn.currency.upper(),
                quantity=txn.quantity,
                price=txn.price,
                fees=txn.fees,
                amount=txn.amount,
                split_ratio=txn.split_ratio,
            )
            for txn in transactions
        ]
        self._session.add_all(rows)
        await self._session.commit()
        return len(rows)

    async def upsert_holding(
        self,
        portfolio_id: int,
        ticker: str,
        sector: str | None = None,
        industry: str | None = None,
        *,
        classification_source: ClassificationSource | None = None,
        clear_fields: tuple[str, ...] = (),
    ) -> None:
        stmt = select(models.Holding).where(
            models.Holding.portfolio_id == portfolio_id,
            models.Holding.ticker == ticker,
        )
        existing = (await self._session.scalars(stmt)).first()
        if existing is None:
            self._session.add(
                models.Holding(
                    portfolio_id=portfolio_id,
                    ticker=ticker,
                    sector=sector,
                    industry=industry,
                    classification_source=(
                        classification_source
                        or (
                            ClassificationSource.MANUAL
                            if sector or industry
                            else ClassificationSource.NONE
                        )
                    ).value,
                )
            )
        else:
            # Only overwrite with a real value; never blank out prior classification.
            if sector is not None:
                existing.sector = sector
            if industry is not None:
                existing.industry = industry
            if "sector" in clear_fields:
                existing.sector = None
            if "industry" in clear_fields:
                existing.industry = None
            if classification_source is not None:
                existing.classification_source = classification_source.value
            elif sector is not None or industry is not None:
                existing.classification_source = ClassificationSource.MANUAL.value
        await self._session.commit()
