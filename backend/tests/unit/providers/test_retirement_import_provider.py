"""Atomic retirement ownership and exact persistence using disposable SQLite fixtures."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio import models
from app.portfolio.accounts import (
    AccountConflict,
    AccountNotFound,
    AccountUpdate,
    SecurityAlias,
    SecurityCreate,
    ValuationCreate,
    ValuationPositionInput,
    canonical_snapshot_hash,
)
from app.portfolio.vanguard import ImportOptions, fund_alias, parse_vanguard
from app.providers.account_provider import SqlAlchemyAccountProvider
from app.providers.retirement_import_provider import SqlAlchemyRetirementImportProvider
from tests.vanguard_fixtures import OPTIONS, export


async def seed(session: AsyncSession, external: str | None = None) -> int:
    row = models.Portfolio(
        name="Fictitious Retirement", base_currency="USD", external_account_id=external
    )
    session.add(row)
    await session.commit()
    return row.id


async def commit_source(
    provider: SqlAlchemyRetirementImportProvider,
    portfolio_id: int,
    content: bytes,
    options: ImportOptions = OPTIONS,
):
    parsed = parse_vanguard(content)
    preview = await provider.preview(portfolio_id, parsed, options)
    return await provider.commit(
        portfolio_id, parsed, options, preview.preview_token, f"vanguard-{parsed.checksum}.csv"
    )


async def test_read_only_preview_atomic_commit_reload_and_no_legacy_side_effects(
    async_session: AsyncSession,
) -> None:
    pid = await seed(async_session)
    provider = SqlAlchemyRetirementImportProvider(async_session)
    parsed = parse_vanguard(
        export(
            extra_activity="42,01/03/2026,02/02/2026,114001,Plan Contribution,Fictional Growth,10.003,2,20.01,\n"
        )
    )
    preview = await provider.preview(pid, parsed, OPTIONS)
    assert preview.can_commit
    for model in (
        models.RetirementImport,
        models.Security,
        models.SecurityAlias,
        models.AccountValuation,
        models.RetirementActivity,
    ):
        assert await async_session.scalar(select(func.count()).select_from(model)) == 0
    row = await async_session.get(models.Portfolio, pid)
    assert row is not None and row.external_account_id is None
    stored = await provider.commit(pid, parsed, OPTIONS, preview.preview_token, "vanguard-test.csv")
    assert stored.preview.source == parsed and stored.status == "COMMITTED"
    assert stored.preview.funds[0].security_id is not None
    assert await provider.detail(pid, stored.id) == stored
    assert await provider.history(pid) == (stored,)
    activities = await provider.activity(pid)
    assert len(activities) == 2 and activities[0].id != activities[1].id
    assert activities[0].fact.fingerprint == activities[1].fact.fingerprint
    assert activities[0].fact.account_number == "000042"
    assert activities[0].fact.amount == Decimal("20.01")
    assert activities[0].fact.checksum == parsed.checksum
    assert (
        row.external_account_id == "000042"
        and row.custodian == "Vanguard"
        and row.account_type == "UNKNOWN"
    )
    snapshot = await SqlAlchemyAccountProvider(async_session).latest_valuation(pid)
    assert snapshot is not None and snapshot.data.positions[0].quantity == Decimal("10.0000000001")
    assert snapshot.data.positions[0].cost_basis is None
    security = await async_session.get(models.Security, activities[0].security_id)
    assert (
        security is not None and security.ticker is None and security.instrument_type == "UNKNOWN"
    )
    for model in (models.Transaction, models.Holding, models.Cash, models.StatementImport):
        assert await async_session.scalar(select(func.count()).select_from(model)) == 0


async def test_duplicate_overlap_genuine_mismatch_and_missing_resources(
    async_session: AsyncSession,
) -> None:
    pid = await seed(async_session, "00000042")
    provider = SqlAlchemyRetirementImportProvider(async_session)
    await commit_source(provider, pid, export())
    with pytest.raises(AccountConflict, match="duplicate"):
        await commit_source(provider, pid, export())
    with pytest.raises(AccountConflict, match="overlapping"):
        await commit_source(provider, pid, export(units="11"))
    other = await seed(async_session, "43")
    with pytest.raises(AccountConflict, match="bound"):
        await commit_source(provider, other, export())
    for operation in (
        provider.preview(999, parse_vanguard(export()), OPTIONS),
        provider.history(999),
        provider.detail(pid, 999),
        provider.activity(999),
    ):
        with pytest.raises(AccountNotFound):
            await operation
    assert len(await provider.history(pid)) == 1


async def test_existing_mapping_reused_and_no_cross_plan_conflation(
    async_session: AsyncSession,
) -> None:
    pid = await seed(async_session)
    accounts = SqlAlchemyAccountProvider(async_session)
    explicit = await accounts.create_security(
        SecurityCreate(
            name="Explicit Fictional Fund Class",
            ticker="FICT",
            currency="USD",
            aliases=(
                SecurityAlias(
                    source_code="VANGUARD", value=fund_alias("42", "42", "Fictional Growth")
                ),
            ),
        )
    )
    provider = SqlAlchemyRetirementImportProvider(async_session)
    stored = await commit_source(provider, pid, export())
    assert (
        stored.preview.funds[0].security_id == explicit.id
        and stored.preview.funds[0].ticker == "FICT"
    )
    second = await seed(async_session)
    await commit_source(provider, second, export().replace(b"42", b"43"))
    assert await async_session.scalar(select(func.count()).select_from(models.Security)) == 2


async def test_failure_rolls_back_binding_security_aliases_snapshot_and_retry_is_safe(
    async_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = await seed(async_session)
    provider = SqlAlchemyRetirementImportProvider(async_session)
    accounts = provider._accounts
    original = accounts.write_valuation
    monkeypatch.setattr(
        accounts,
        "write_valuation",
        AsyncMock(side_effect=RuntimeError("injected DB failure after aliases")),
    )
    with pytest.raises(RuntimeError, match="injected"):
        await commit_source(provider, pid, export())
    for model in (
        models.Security,
        models.SecurityAlias,
        models.AccountValuation,
        models.RetirementImport,
        models.RetirementActivity,
    ):
        assert await async_session.scalar(select(func.count()).select_from(model)) == 0
    portfolio = await async_session.get(models.Portfolio, pid)
    assert (
        portfolio is not None
        and portfolio.external_account_id is None
        and portfolio.custodian is None
    )
    monkeypatch.setattr(accounts, "write_valuation", original)
    stored = await commit_source(provider, pid, export())
    assert len(await provider.activity(pid)) == 1
    assert len(await provider.history(pid)) == 1 and stored.preview.reported_total == Decimal(
        "100.05"
    )


async def test_failure_after_activity_flush_rolls_back_every_owned_row(
    async_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = await seed(async_session)
    provider = SqlAlchemyRetirementImportProvider(async_session)
    original = async_session.flush

    async def fail_on_activity(*args: object, **kwargs: object) -> None:
        if any(isinstance(row, models.RetirementActivity) for row in async_session.new):
            raise RuntimeError("activity write failure")
        await original()

    monkeypatch.setattr(async_session, "flush", fail_on_activity)
    with pytest.raises(RuntimeError, match="activity"):
        await commit_source(provider, pid, export())
    monkeypatch.setattr(async_session, "flush", original)
    for model in (
        models.Security,
        models.SecurityAlias,
        models.AccountValuation,
        models.RetirementImport,
        models.RetirementActivity,
    ):
        assert await async_session.scalar(select(func.count()).select_from(model)) == 0
    await commit_source(provider, pid, export())


async def test_stale_preview_options_account_mapping_and_snapshot_state(
    async_session: AsyncSession,
) -> None:
    pid = await seed(async_session)
    provider = SqlAlchemyRetirementImportProvider(async_session)
    parsed = parse_vanguard(export())
    preview = await provider.preview(pid, parsed, OPTIONS)
    with pytest.raises(AccountConflict, match="stale"):
        await provider.commit(
            pid,
            parsed,
            OPTIONS.model_copy(update={"as_of": date(2026, 2, 1)}),
            preview.preview_token,
            "unused",
        )
    accounts = SqlAlchemyAccountProvider(async_session)
    await accounts.update_account(pid, AccountUpdate(custodian="Changed"))
    with pytest.raises(AccountConflict, match="stale"):
        await provider.commit(pid, parsed, OPTIONS, preview.preview_token, "unused")
    preview = await provider.preview(pid, parsed, OPTIONS)
    security = await accounts.create_security(
        SecurityCreate(
            name="Manual",
            currency="USD",
            aliases=(
                SecurityAlias(
                    source_code="VANGUARD", value=fund_alias("42", "42", "Fictional Growth")
                ),
            ),
        )
    )
    with pytest.raises(AccountConflict, match="stale"):
        await provider.commit(pid, parsed, OPTIONS, preview.preview_token, "unused")
    preview = await provider.preview(pid, parsed, OPTIONS)
    value = ValuationCreate(
        as_of=date(2025, 12, 31),
        currency="USD",
        positions=(
            ValuationPositionInput(
                security_id=security.id, quantity=Decimal(1), reported_value=Decimal(2)
            ),
        ),
    )
    await accounts.write_valuation(pid, value, canonical_snapshot_hash(value))
    with pytest.raises(AccountConflict, match="stale"):
        await provider.commit(pid, parsed, OPTIONS, preview.preview_token, "unused")
    assert await provider.history(pid) == ()


async def test_same_date_conflict_has_no_alias_leak_and_latest_uses_asof_not_import_time(
    async_session: AsyncSession,
) -> None:
    pid = await seed(async_session)
    provider = SqlAlchemyRetirementImportProvider(async_session)
    first = await commit_source(provider, pid, export())
    # Nonoverlapping activity does not exempt conflicting same-date source snapshots.
    conflict = export(trade="01/04/2026", fund="Other Fictitious Fund")
    with pytest.raises(AccountConflict, match="snapshot"):
        await commit_source(provider, pid, conflict)
    assert await async_session.scalar(select(func.count()).select_from(models.Security)) == 1
    older_options = OPTIONS.model_copy(update={"as_of": date(2026, 1, 15)})
    older = await commit_source(provider, pid, conflict, older_options)
    assert (await provider.history(pid))[0].id == older.id
    latest = await SqlAlchemyAccountProvider(async_session).latest_valuation(pid)
    assert latest is not None and latest.id == first.valuation_id


async def test_blockers_do_not_write_anything(async_session: AsyncSession) -> None:
    pid = await seed(async_session)
    provider = SqlAlchemyRetirementImportProvider(async_session)
    with pytest.raises(AccountConflict, match="blocking"):
        await commit_source(provider, pid, export(code="999"))
    assert await provider.history(pid) == ()
    assert await async_session.scalar(select(func.count()).select_from(models.Security)) == 0


async def test_activity_retains_funds_closed_in_later_snapshots(
    async_session: AsyncSession,
) -> None:
    pid = await seed(async_session)
    provider = SqlAlchemyRetirementImportProvider(async_session)
    first = await commit_source(provider, pid, export())
    later = OPTIONS.model_copy(update={"as_of": date(2026, 2, 28)})
    await commit_source(provider, pid, export(fund="New Fictional Fund", trade="02/01/2026"), later)
    snapshot = await SqlAlchemyAccountProvider(async_session).latest_valuation(pid)
    assert snapshot is not None and len(snapshot.data.positions) == 1
    activities = await provider.activity(pid)
    assert len(activities) == 2
    assert activities[0].import_id == first.id
    assert activities[0].fact.fund_name == "Fictional Growth"
    assert activities[1].fact.fund_name == "New Fictional Fund"
    assert activities[0].security_id != snapshot.data.positions[0].security_id
