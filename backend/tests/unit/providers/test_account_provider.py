"""Offline SQLAlchemy round trips and composition rollback using project fixtures."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio import models
from app.portfolio.accounts import (
    AccountConflict,
    AccountNotFound,
    AccountUpdate,
    AccountValidationError,
    SecurityAlias,
    SecurityCreate,
    ValuationCreate,
    ValuationPositionInput,
    canonical_snapshot_hash,
)
from app.portfolio.schemas import AccountType, PortfolioCreate
from app.providers.account_provider import SqlAlchemyAccountProvider
from app.providers.portfolio_provider import SqlAlchemyPortfolioProvider


async def seed(session: AsyncSession) -> tuple[SqlAlchemyAccountProvider, int, int]:
    old = SqlAlchemyPortfolioProvider(session)
    portfolio = await old.create_portfolio(
        PortfolioCreate(name="Fictitious retirement", base_currency="USD")
    )
    provider = SqlAlchemyAccountProvider(session)
    security = await provider.create_security(
        SecurityCreate(name="Fictitious Trust", currency="USD")
    )
    return provider, portfolio.id, security.id


def data(security_id: int, day: int = 31, value: str = "100.0123456789") -> ValuationCreate:
    return ValuationCreate(
        as_of=date(2026, 1, day),
        currency="USD",
        source_reference="fictitious statement",
        positions=(
            ValuationPositionInput(
                security_id=security_id,
                quantity=Decimal("0.0123456789"),
                reported_value=Decimal(value),
            ),
        ),
    )


async def test_account_create_patch_and_existing_read_preserve_identifier(
    async_session: AsyncSession,
) -> None:
    legacy = SqlAlchemyPortfolioProvider(async_session)
    account = await legacy.create_portfolio(
        PortfolioCreate(
            name="Fictitious",
            base_currency="USD",
            account_type=AccountType.TRADITIONAL_401K,
            custodian="Fictitious Custodian",
            external_account_id="00000123",
        )
    )
    provider = SqlAlchemyAccountProvider(async_session)
    updated = await provider.update_account(account.id, AccountUpdate(custodian=None))
    assert updated.custodian is None
    assert updated.external_account_id == "00000123"
    assert updated.account_type == AccountType.TRADITIONAL_401K
    assert await legacy.get_portfolio(account.id) == updated
    assert await legacy.list_portfolios() == [updated]
    with pytest.raises(AccountNotFound):
        await provider.update_account(999, AccountUpdate(external_account_id="000"))


async def test_alias_scope_distinct_classes_and_duplicate_rollback(
    async_session: AsyncSession,
) -> None:
    provider = SqlAlchemyAccountProvider(async_session)
    first = await provider.create_security(
        SecurityCreate(
            name="Fictitious Target 2050 Class A",
            instrument_type="TARGET_DATE_FUND",
            currency="USD",
            aliases=(SecurityAlias(source_code="BROKER_A", value="0001"),),
        )
    )
    second = await provider.create_security(
        SecurityCreate(
            name="Fictitious Target 2050 Class B",
            instrument_type="COLLECTIVE_TRUST",
            currency="USD",
            aliases=(SecurityAlias(source_code="BROKER_B", value="0001"),),
        )
    )
    assert first.id != second.id and first.ticker is None and second.ticker is None
    with pytest.raises(AccountConflict):
        await provider.create_security(
            SecurityCreate(
                name="Do not persist",
                currency="USD",
                aliases=first.aliases,
            )
        )
    securities = await provider.list_securities()
    assert securities == (first, second)
    assert securities[0].aliases[0].value == "0001"


async def test_snapshot_repeat_conflict_history_and_no_ledger_side_effects(
    async_session: AsyncSession,
) -> None:
    provider, portfolio_id, security_id = await seed(async_session)
    request = data(security_id)
    first = await provider.write_valuation(portfolio_id, request, canonical_snapshot_hash(request))
    repeated = await provider.write_valuation(
        portfolio_id, request, canonical_snapshot_hash(request)
    )
    assert repeated == first
    assert first.data.positions[0].reported_value == Decimal("100.0123456789")
    assert first.data.positions[0].quantity == Decimal("0.0123456789")
    assert first.data.positions[0].cost_basis is None
    changed = data(security_id, value="200")
    with pytest.raises(AccountConflict):
        await provider.write_valuation(portfolio_id, changed, canonical_snapshot_hash(changed))
    older = data(security_id, day=1)
    await provider.write_valuation(portfolio_id, older, canonical_snapshot_hash(older))
    assert await provider.latest_valuation(portfolio_id) == first
    assert (
        await async_session.scalar(select(func.count()).select_from(models.AccountValuation)) == 2
    )
    for table in (models.Transaction, models.Holding, models.Cash):
        assert await async_session.scalar(select(func.count()).select_from(table)) == 0


async def test_invalid_security_or_currency_is_whole_snapshot_rollback(
    async_session: AsyncSession,
) -> None:
    provider, portfolio_id, security_id = await seed(async_session)
    request = data(security_id)
    invalid = request.model_copy(update={"positions": request.positions + data(999).positions})
    for bad in (invalid, request.model_copy(update={"currency": "INR"})):
        with pytest.raises(AccountValidationError):
            await provider.write_valuation(portfolio_id, bad, canonical_snapshot_hash(bad))
    other_currency = await provider.create_security(
        SecurityCreate(name="Fictitious INR", currency="INR")
    )
    wrong_security = data(other_currency.id)
    with pytest.raises(AccountValidationError):
        await provider.write_valuation(
            portfolio_id, wrong_security, canonical_snapshot_hash(wrong_security)
        )
    assert (
        await async_session.scalar(select(func.count()).select_from(models.AccountValuation)) == 0
    )
    assert (
        await async_session.scalar(
            select(func.count()).select_from(models.AccountValuationPosition)
        )
        == 0
    )
    with pytest.raises(AccountNotFound):
        await provider.write_valuation(999, request, canonical_snapshot_hash(request))
    with pytest.raises(AccountNotFound):
        await provider.latest_valuation(999)


async def test_composed_security_snapshot_and_future_activity_share_atomic_rollback(
    async_session: AsyncSession,
) -> None:
    provider, portfolio_id, _ = await seed(async_session)
    with pytest.raises(RuntimeError, match="activity failed"):
        async with provider.transaction():
            security = await provider.create_security(
                SecurityCreate(
                    name="Atomic Class",
                    currency="USD",
                    aliases=(SecurityAlias(source_code="TEST", value="001"),),
                )
            )
            request = data(security.id)
            await provider.write_valuation(portfolio_id, request, canonical_snapshot_hash(request))
            raise RuntimeError("activity failed")
    assert len(await provider.list_securities()) == 1
    assert await provider.latest_valuation(portfolio_id) is None
    assert await async_session.scalar(select(func.count()).select_from(models.SecurityAlias)) == 0
    async with provider.transaction():
        security = await provider.create_security(
            SecurityCreate(name="Atomic success", currency="USD")
        )
        request = data(security.id)
        await provider.write_valuation(portfolio_id, request, canonical_snapshot_hash(request))
    assert len(await provider.list_securities()) == 2
    assert await provider.latest_valuation(portfolio_id) is not None


@pytest.mark.parametrize("aware", [False, True])
async def test_imported_provenance_preserves_instant(
    async_session: AsyncSession,
    aware: bool,
) -> None:
    provider = SqlAlchemyAccountProvider(async_session)
    clock = (
        datetime(2026, 2, 1, 7, tzinfo=timezone(timedelta(hours=5)))
        if aware
        else datetime(2026, 2, 1, 2)
    )
    row = models.AccountValuation(
        id=1,
        portfolio_id=1,
        as_of=date(2026, 1, 31),
        currency="USD",
        complete_snapshot=True,
        content_hash="a" * 64,
        source_code="TEST",
        source_reference=None,
        imported_at=clock,
    )
    stored = await provider._stored(row)
    assert stored.imported_at == datetime(2026, 2, 1, 2, tzinfo=UTC)
