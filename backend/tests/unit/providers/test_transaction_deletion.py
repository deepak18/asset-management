from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency import FxRateTable
from app.portfolio import models
from app.portfolio.history import TransactionDeletionConflict
from app.portfolio.holding_analytics import HoldingAnalyticsService
from app.portfolio.schemas import (
    HoldingHistoryGap,
    HoldingReturnStatus,
    ImportIssue,
    LedgerOrigin,
    PortfolioCreate,
    Transaction,
    TransactionType,
    UnresolvedKind,
)
from app.providers.portfolio_provider import SqlAlchemyPortfolioProvider
from app.providers.statement_import_store import SqlAlchemyStatementImportStore


def buy() -> Transaction:
    return Transaction(
        ticker="AAA", type=TransactionType.BUY, trade_date=date(2024, 1, 1),
        currency="USD", quantity=Decimal("10"), price=Decimal("100"),
    )


async def setup(session: AsyncSession) -> tuple[int, SqlAlchemyPortfolioProvider]:
    provider = SqlAlchemyPortfolioProvider(session)
    summary = await provider.create_portfolio(PortfolioCreate(name="Delete", base_currency="USD"))
    await provider.add_transactions(summary.id, [buy()])
    await provider.upsert_holding(summary.id, "AAA", "Technology", "Hardware")
    return summary.id, provider


async def test_delete_one_of_identical_rows_by_stable_id(async_session: AsyncSession) -> None:
    pid, provider = await setup(async_session)
    await provider.add_transactions(pid, [buy()])
    records = await provider.list_transaction_records(pid)
    first_id, second_id = (row.id for row in records)
    assert first_id != second_id
    assert await provider.delete_transaction(pid, first_id)
    assert [row.id for row in await provider.list_transaction_records(pid)] == [second_id]
    assert len(await provider.list_transactions(pid)) == 1
    async_session.expire_all()
    holding = await SqlAlchemyPortfolioProvider(async_session).get_holding(pid, "aaa")
    assert holding is not None and not holding.history_complete
    assert holding.history_gaps == (HoldingHistoryGap.DELETED_TRANSACTION,)
    assert holding.sector == "Technology" and holding.industry == "Hardware"
    ledger = await provider.get_holding_ledger(pid, "AAA")
    assert ledger.has_deleted_transactions and len(ledger.transactions) == 1
    result = await HoldingAnalyticsService(provider, FxRateTable(base_currency="USD")).get_analytics(pid, "AAA")
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == HoldingReturnStatus.INCOMPLETE_HISTORY
    row = await async_session.get(models.Transaction, first_id)
    assert row is not None and row.deleted_at is not None
    assert not await provider.delete_transaction(pid, first_id)


async def test_missing_and_cross_portfolio_ids_do_not_delete(async_session: AsyncSession) -> None:
    pid, provider = await setup(async_session)
    record = (await provider.list_transaction_records(pid))[0]
    other = await provider.create_portfolio(PortfolioCreate(name="Other", base_currency="USD"))
    assert not await provider.delete_transaction(other.id, record.id)
    assert not await provider.delete_transaction(99999, record.id)
    assert not await provider.delete_transaction(pid, 99999)
    assert [row.id for row in await provider.list_transaction_records(pid)] == [record.id]


async def test_dependent_sale_conflict_and_remove_sale_first(async_session: AsyncSession) -> None:
    pid, provider = await setup(async_session)
    await provider.add_transactions(pid, [buy().model_copy(update={
        "type": TransactionType.SELL, "quantity": Decimal("4"), "trade_date": date(2024, 2, 1),
    })])
    purchase, sale = await provider.list_transaction_records(pid)
    purchase_id, sale_id = purchase.id, sale.id
    with pytest.raises(TransactionDeletionConflict, match="without enough shares"):
        await provider.delete_transaction(pid, purchase_id)
    assert len(await provider.list_transactions(pid)) == 2
    assert await provider.delete_transaction(pid, sale_id)
    assert await provider.delete_transaction(pid, purchase_id)
    assert await provider.list_transactions(pid) == []
    holding = await provider.get_holding(pid, "AAA")
    assert holding is not None and not holding.history_complete
    assert set(holding.history_gaps) == {HoldingHistoryGap.DELETED_TRANSACTION, HoldingHistoryGap.NO_TRANSACTIONS}


@pytest.mark.parametrize("running", [False, True])
async def test_active_import_conflict_leaves_row_untouched(
    async_session: AsyncSession, running: bool,
) -> None:
    pid, provider = await setup(async_session)
    record_id = (await provider.list_transaction_records(pid))[0].id
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(pid, "robinhood_csv", "rh.csv", "key", "a" * 64, 1, True)
    if running:
        assert await store.claim_job(job.id)
    with pytest.raises(TransactionDeletionConflict, match="pending/running"):
        await provider.delete_transaction(pid, record_id)
    assert len(await provider.list_transactions(pid)) == 1
    row = await async_session.get(models.Transaction, record_id)
    assert row is not None and row.deleted_at is None


async def test_imported_deletion_disables_retry_and_guard_survives_flag_reset(
    async_session: AsyncSession,
) -> None:
    provider = SqlAlchemyPortfolioProvider(async_session)
    summary = await provider.create_portfolio(PortfolioCreate(name="Import", base_currency="USD"))
    pid = summary.id
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(pid, "robinhood_csv", "rh.csv", "key", "a" * 64, 1, True)
    assert await store.claim_job(job.id)
    await store.append_batch(job.id, [buy()])
    await store.mark_failed(job.id, "interrupted")
    record_id = (await provider.list_transaction_records(pid))[0].id
    assert await provider.delete_transaction(pid, record_id)
    stored = await store.get_job(job.id)
    assert stored is not None and not stored.retry_safe
    with pytest.raises(ValueError, match="deleted events"):
        await store.reset_failed(pid, job.id)
    # Defense in depth: tombstone guard does not rely solely on the metadata flag.
    row = await async_session.get(models.StatementImport, job.id)
    assert row is not None
    row.retry_safe = True
    await async_session.commit()
    with pytest.raises(ValueError, match="deleted events"):
        await store.reset_failed(pid, job.id)
    assert await provider.list_transactions(pid) == []
    assert (await async_session.get(models.Transaction, record_id)) is not None


async def test_unknown_legacy_deletion_disables_ambiguous_account_retries(async_session: AsyncSession) -> None:
    pid, provider = await setup(async_session)
    record_id = (await provider.list_transaction_records(pid))[0].id
    row = await async_session.get(models.Transaction, record_id)
    assert row is not None
    row.history_origin = LedgerOrigin.UNKNOWN
    await async_session.commit()
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(pid, "robinhood_csv", "rh.csv", "key", "a" * 64, 1)
    await store.mark_failed(job.id, "old failure")
    assert await provider.delete_transaction(pid, record_id)
    stored = await store.get_job(job.id)
    assert stored is not None and not stored.retry_safe


async def test_failed_commit_rolls_back_deletion_and_retry_flag(
    async_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid, provider = await setup(async_session)
    record_id = (await provider.list_transaction_records(pid))[0].id
    row = await async_session.get(models.Transaction, record_id)
    assert row is not None
    row.history_origin = LedgerOrigin.UNKNOWN
    await async_session.commit()
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(pid, "robinhood_csv", "rh.csv", "key", "a" * 64, 1)
    await store.mark_failed(job.id, "old failure")
    real_commit = async_session.commit

    async def fail_commit() -> None:
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(async_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit failure"):
        await provider.delete_transaction(pid, record_id)
    monkeypatch.setattr(async_session, "commit", real_commit)
    stored = await store.get_job(job.id)
    assert stored is not None and stored.retry_safe
    record = await async_session.get(models.Transaction, record_id)
    assert record is not None and record.deleted_at is None
    assert len(await provider.list_transactions(pid)) == 1


async def test_deleting_correction_does_not_claim_source_is_repaired(
    async_session: AsyncSession,
) -> None:
    pid, provider = await setup(async_session)
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(pid, "robinhood_csv", "rh.csv", "key", "a" * 64, 1, True)
    await store.mark_succeeded(job.id, 0, [], [], [ImportIssue(
        kind=UnresolvedKind.UNSUPPORTED_ROW, source_line=2, ticker="AAA",
    )])
    item = (await store.list_unresolved(pid))[0]
    await store.resolve_item(pid, item.id, buy().model_copy(update={"type": TransactionType.DIVIDEND, "amount": Decimal("5")}))
    correction_id = (await provider.list_transaction_records(pid))[-1].id
    assert await provider.delete_transaction(pid, correction_id)
    holding = await provider.get_holding(pid, "AAA")
    assert holding is not None and not holding.history_complete
    assert HoldingHistoryGap.DELETED_TRANSACTION in holding.history_gaps
    # Resolution audit is not rewritten or reopened; repeated repair cannot duplicate it.
    with pytest.raises(ValueError, match="already resolved"):
        await store.resolve_item(pid, item.id, buy())
    assert await async_session.scalar(select(models.Transaction.id).where(models.Transaction.id == correction_id)) == correction_id
