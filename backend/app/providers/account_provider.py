"""Typed persistence boundary for shared identities and whole reported snapshots.

Use ``async with provider.transaction():`` to compose securities, valuations and
future activity writes on the same session. Nested operations flush, never commit
individually. The outer provider transaction owns commit/rollback.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio import models
from app.portfolio.accounts import (
    AccountConflict,
    AccountNotFound,
    AccountUpdate,
    SecurityAlias,
    SecurityCreate,
    SecurityInfo,
    StoredValuation,
    ValuationCreate,
    ValuationPositionInput,
    validate_snapshot_currency,
)
from app.portfolio.schemas import PortfolioSummary


class AccountProvider(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]: ...
    async def update_account(self, portfolio_id: int, data: AccountUpdate) -> PortfolioSummary: ...
    async def create_security(self, data: SecurityCreate) -> SecurityInfo: ...
    async def list_securities(self) -> tuple[SecurityInfo, ...]: ...
    async def write_valuation(
        self,
        portfolio_id: int,
        data: ValuationCreate,
        content_hash: str,
    ) -> StoredValuation: ...
    async def latest_valuation(self, portfolio_id: int) -> StoredValuation | None: ...


class SqlAlchemyAccountProvider:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._composing = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        if self._composing:
            yield
            return
        self._composing = True
        try:
            async with self._session.begin_nested():
                yield
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise
        finally:
            self._composing = False

    async def _portfolio(self, portfolio_id: int, *, lock: bool = False) -> models.Portfolio:
        stmt = select(models.Portfolio).where(models.Portfolio.id == portfolio_id)
        if lock:
            stmt = stmt.with_for_update()
        row = await self._session.scalar(stmt)
        if row is None:
            raise AccountNotFound("portfolio not found")
        return row

    async def update_account(self, portfolio_id: int, data: AccountUpdate) -> PortfolioSummary:
        async with self.transaction():
            row = await self._portfolio(portfolio_id, lock=True)
            if "account_type" in data.model_fields_set:
                row.account_type = data.account_type.value
            if "custodian" in data.model_fields_set:
                row.custodian = data.custodian
            if "external_account_id" in data.model_fields_set:
                row.external_account_id = data.external_account_id
            await self._session.flush()
            result = PortfolioSummary.model_validate(row, from_attributes=True)
        return result

    async def _security(self, row: models.Security) -> SecurityInfo:
        aliases = (
            await self._session.scalars(
                select(models.SecurityAlias)
                .where(
                    models.SecurityAlias.security_id == row.id,
                )
                .order_by(models.SecurityAlias.source_code, models.SecurityAlias.value)
            )
        ).all()
        return SecurityInfo(
            id=row.id,
            name=row.name,
            instrument_type=row.instrument_type,
            ticker=row.ticker,
            currency=row.currency,
            aliases=tuple(SecurityAlias(source_code=a.source_code, value=a.value) for a in aliases),
        )

    async def create_security(self, data: SecurityCreate) -> SecurityInfo:
        try:
            async with self.transaction():
                row = models.Security(
                    name=data.name,
                    instrument_type=data.instrument_type.value,
                    ticker=data.ticker,
                    currency=data.currency,
                )
                self._session.add(row)
                await self._session.flush()
                self._session.add_all(
                    models.SecurityAlias(
                        security_id=row.id,
                        source_code=a.source_code,
                        value=a.value,
                    )
                    for a in data.aliases
                )
                await self._session.flush()
                result = await self._security(row)
            return result
        except IntegrityError as exc:
            raise AccountConflict("source-scoped security identity already exists") from exc

    async def list_securities(self) -> tuple[SecurityInfo, ...]:
        rows = (
            await self._session.scalars(select(models.Security).order_by(models.Security.id))
        ).all()
        return tuple([await self._security(row) for row in rows])

    async def _stored(self, row: models.AccountValuation) -> StoredValuation:
        positions = (
            await self._session.scalars(
                select(models.AccountValuationPosition)
                .where(
                    models.AccountValuationPosition.valuation_id == row.id,
                )
                .order_by(models.AccountValuationPosition.security_id)
            )
        ).all()
        return StoredValuation(
            id=row.id,
            portfolio_id=row.portfolio_id,
            # SQLite drops timezone information; the persisted clock is always UTC.
            imported_at=(
                row.imported_at.replace(tzinfo=UTC)
                if row.imported_at.tzinfo is None
                else row.imported_at.astimezone(UTC)
            ),
            data=ValuationCreate(
                as_of=row.as_of,
                currency=row.currency,
                complete_snapshot=row.complete_snapshot,
                source_code=row.source_code,
                source_reference=row.source_reference,
                positions=tuple(
                    ValuationPositionInput.model_validate(p, from_attributes=True)
                    for p in positions
                ),
            ),
        )

    async def _same_date(
        self, portfolio_id: int, data: ValuationCreate
    ) -> models.AccountValuation | None:
        row: models.AccountValuation | None = await self._session.scalar(
            select(models.AccountValuation).where(
                models.AccountValuation.portfolio_id == portfolio_id,
                models.AccountValuation.as_of == data.as_of,
            )
        )
        return row

    async def write_valuation(
        self,
        portfolio_id: int,
        data: ValuationCreate,
        content_hash: str,
    ) -> StoredValuation:
        try:
            async with self.transaction():
                portfolio = await self._portfolio(portfolio_id, lock=True)
                ids = tuple(p.security_id for p in data.positions)
                securities = (
                    await self._session.scalars(
                        select(models.Security).where(
                            models.Security.id.in_(ids),
                        )
                    )
                ).all()
                validate_snapshot_currency(
                    data,
                    portfolio.base_currency,
                    tuple([await self._security(security) for security in securities]),
                )
                existing = await self._same_date(portfolio_id, data)
                if existing is not None:
                    if existing.content_hash != content_hash:
                        raise AccountConflict("different snapshot already exists for this date")
                    return await self._stored(existing)
                row = models.AccountValuation(
                    portfolio_id=portfolio_id,
                    as_of=data.as_of,
                    currency=data.currency,
                    complete_snapshot=data.complete_snapshot,
                    content_hash=content_hash,
                    source_code=data.source_code,
                    source_reference=data.source_reference,
                    imported_at=datetime.now(UTC),
                )
                self._session.add(row)
                await self._session.flush()
                self._session.add_all(
                    models.AccountValuationPosition(
                        valuation_id=row.id,
                        security_id=p.security_id,
                        quantity=p.quantity,
                        reported_price=p.reported_price,
                        reported_value=p.reported_value,
                        cost_basis=p.cost_basis,
                        source_reference=p.source_reference,
                    )
                    for p in data.positions
                )
                await self._session.flush()
                result = await self._stored(row)
            return result
        except IntegrityError as exc:
            # Unique date constraint arbitrates writers even on dialects without row locks.
            # In a composed transaction let the outer scope roll back as one unit.
            if not self._composing:
                existing = await self._same_date(portfolio_id, data)
                if existing is not None and existing.content_hash == content_hash:
                    return await self._stored(existing)
            raise AccountConflict("snapshot date conflicts with an existing write") from exc

    async def latest_valuation(self, portfolio_id: int) -> StoredValuation | None:
        await self._portfolio(portfolio_id)
        row = await self._session.scalar(
            select(models.AccountValuation)
            .where(
                models.AccountValuation.portfolio_id == portfolio_id,
            )
            .order_by(models.AccountValuation.as_of.desc())
            .limit(1)
        )
        return None if row is None else await self._stored(row)
