"""Persisted confirmation, immutable provenance, and atomic snapshot boundaries."""

from asyncio import Event, create_task, wait_for
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.portfolio import models
from app.portfolio.history import HistoryConfirmationConflict
from app.portfolio.schemas import (
    HistoryTransactionState,
    HoldingHistoryGap,
    ImportIssue,
    ImportStatus,
    LedgerOrigin,
    PortfolioCreate,
    Transaction,
    TransactionType,
    UnresolvedKind,
)
from app.providers.portfolio_provider import SqlAlchemyPortfolioProvider
from app.providers.statement_import_store import SqlAlchemyStatementImportStore


def buy() -> Transaction:
    return Transaction(ticker="AAA", type=TransactionType.BUY, trade_date=date(2024, 1, 1),
                       currency="USD", quantity=Decimal("10"), price=Decimal("100.0123"))


async def seed(session: AsyncSession) -> SqlAlchemyPortfolioProvider:
    provider = SqlAlchemyPortfolioProvider(session)
    await provider.create_portfolio(PortfolioCreate(name="Test", base_currency="USD"))
    await provider.upsert_holding(1, "AAA")
    await provider.add_transactions(1, [buy()])
    return provider


@pytest.mark.parametrize("reason", ["legacy", "incomplete_import", "deleted"])
async def test_acknowledgeable_history_persists_without_rewriting_audit_facts(
    async_session: AsyncSession, reason: str,
) -> None:
    provider = await seed(async_session)
    store = SqlAlchemyStatementImportStore(async_session)
    if reason == "legacy":
        row = await async_session.scalar(select(models.Transaction))
        assert row is not None
        row.history_origin = LedgerOrigin.UNKNOWN
        await async_session.commit()
    elif reason == "incomplete_import":
        job = await store.create_job(1, "robinhood_csv", "test.csv", "raw", "a" * 64, 1)
        await store.mark_succeeded(job.id, 0, ["AAA"], [])
    else:
        await provider.add_transactions(1, [buy()])
        assert await provider.delete_transaction(1, 2)
    before = await provider.get_history_review(1, "aaa")
    assert before is not None and not before.history_complete
    assert before.confirmed_at is None and before.blocking_gaps == ()
    confirmed = await provider.confirm_history(1, "AAA", before.review_token)
    assert confirmed is not None and confirmed.history_complete
    assert confirmed.confirmed_at is not None and confirmed.history_gaps == ()
    assert confirmed.transactions == before.transactions
    assert confirmed.review_token == before.review_token
    assert tuple(await provider.list_transaction_records(1)) == confirmed.transactions
    async_session.expunge_all()
    assert await provider.get_history_review(1, "aaa") == confirmed
    assert await provider.confirm_history(1, "aaa", before.review_token) == confirmed
    holding = await provider.get_holding(1, "AAA")
    assert holding is not None and holding.history_complete
    assert (await provider.list_holdings(1))[0].history_complete
    if reason == "legacy":
        assert before.transactions[0].history_origin is LedgerOrigin.UNKNOWN
        assert confirmed.transactions[0].history_origin is LedgerOrigin.UNKNOWN
        row = await async_session.scalar(select(models.Transaction))
        assert row is not None and row.history_origin == LedgerOrigin.UNKNOWN
    if reason == "incomplete_import":
        assert not (await store.list_jobs(1))[0].history_complete


@pytest.mark.parametrize("change", ["add", "delete", "job_status", "job_complete", "unresolved"])
async def test_changes_invalidate_confirmation_and_reject_old_token(
    async_session: AsyncSession, change: str,
) -> None:
    provider = await seed(async_session)
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(1, "robinhood_csv", "test.csv", "raw", "a" * 64, 1, True)
    await store.mark_succeeded(job.id, 0, ["AAA"], [])
    review = await provider.get_history_review(1, "AAA")
    assert review is not None
    confirmed = await provider.confirm_history(1, "AAA", review.review_token)
    assert confirmed is not None and confirmed.confirmed_at is not None
    if change == "add":
        await provider.add_transactions(1, [buy()])
    elif change == "delete":
        assert await provider.delete_transaction(1, review.transactions[0].id)
    elif change == "job_status":
        await store.mark_failed(job.id, "failure")
    elif change == "job_complete":
        row = await async_session.get(models.StatementImport, job.id)
        assert row is not None
        row.history_complete = False
        await async_session.commit()
    else:
        await store.mark_succeeded(job.id, 0, ["AAA"], [], [ImportIssue(
            kind=UnresolvedKind.UNSUPPORTED_ROW, source_line=2, ticker=None,
        )])
    changed = await provider.get_history_review(1, "AAA")
    assert changed is not None and changed.confirmed_at is None
    assert not changed.history_complete and changed.review_token != review.review_token
    assert HoldingHistoryGap.HISTORY_CHANGED in changed.history_gaps
    with pytest.raises(HistoryConfirmationConflict):
        await provider.confirm_history(1, "AAA", review.review_token)
    holding = await provider.get_holding(1, "AAA")
    assert holding is not None and holding.history_gaps == changed.history_gaps


@pytest.mark.parametrize("status", list(ImportStatus))
async def test_active_imports_block_even_with_known_unrelated_scope(
    async_session: AsyncSession, status: ImportStatus,
) -> None:
    provider = await seed(async_session)
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(1, "robinhood_csv", "test.csv", "raw", "a" * 64, 1, True)
    row = await async_session.get(models.StatementImport, job.id)
    assert row is not None
    row.status = status
    row.tickers_json = '["BBB"]'
    await async_session.commit()
    review = await provider.get_history_review(1, "AAA")
    assert review is not None
    if status in (ImportStatus.PENDING, ImportStatus.RUNNING):
        assert HoldingHistoryGap.IMPORT_NOT_SUCCEEDED in review.blocking_gaps
        with pytest.raises(HistoryConfirmationConflict):
            await provider.confirm_history(1, "AAA", review.review_token)
    else:
        assert review.blocking_gaps == ()


async def test_progress_timestamps_and_unrelated_scope_do_not_change_token(
    async_session: AsyncSession,
) -> None:
    provider = await seed(async_session)
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(1, "robinhood_csv", "test.csv", "raw", "a" * 64, 1, True)
    await store.mark_succeeded(job.id, 0, ["AAA"], [])
    review = await provider.get_history_review(1, "AAA")
    assert review is not None
    await store.record_progress(job.id, 99)
    await provider.upsert_holding(1, "BBB")
    await provider.add_transactions(1, [buy().model_copy(update={"ticker": "BBB"})])
    await provider.create_portfolio(PortfolioCreate(name="Other", base_currency="USD"))
    await provider.upsert_holding(2, "AAA")
    await provider.add_transactions(2, [buy()])
    changed = await provider.get_history_review(1, "AAA")
    assert changed is not None and changed.review_token == review.review_token
    assert changed.transactions == review.transactions
    other = await provider.get_history_review(2, "AAA")
    assert other is not None and other.review_token != review.review_token
    with pytest.raises(HistoryConfirmationConflict):
        await provider.confirm_history(2, "AAA", review.review_token)


async def test_postgres_lock_contention_releases_savepoint_before_retry() -> None:
    class LockUnavailable(Exception):
        sqlstate = "55P03"

    session = AsyncMock(spec=AsyncSession)
    session.get_bind = MagicMock()
    session.get_bind.return_value.dialect.name = "postgresql"
    session.scalar.return_value = models.Portfolio(id=1, name="Test", base_currency="USD")
    nested = MagicMock()
    nested.__aenter__ = AsyncMock()
    nested.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested)
    session.execute.side_effect = [DBAPIError(None, None, LockUnavailable()), None]
    assert await SqlAlchemyPortfolioProvider(session)._lock_history(1)
    assert "FOR NO KEY UPDATE" in str(session.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert nested.__aexit__.await_count == 2
    assert session.execute.await_count == 2
    assert "NOWAIT" in str(session.execute.call_args.args[0])


async def test_concurrent_write_waits_for_review_then_immediately_invalidates(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'concurrent.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda connection: Base.metadata.create_all(connection))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    reached, release, started = Event(), Event(), Event()

    class PausedProvider(SqlAlchemyPortfolioProvider):
        async def _ledger_rows(
            self, portfolio_id: int, ticker: str | None = None,
        ) -> Sequence[models.Transaction]:
            reached.set()
            await release.wait()
            return await super()._ledger_rows(portfolio_id, ticker)

    try:
        async with factory() as setup:
            provider = await seed(setup)
            review = await provider.get_history_review(1, "AAA")
            assert review is not None
        async with factory() as reviewing, factory() as writing:
            task = create_task(PausedProvider(reviewing).confirm_history(1, "AAA", review.review_token))
            await wait_for(reached.wait(), 5)

            async def write() -> None:
                started.set()
                await SqlAlchemyPortfolioProvider(writing).add_transactions(1, [buy()])

            writer = create_task(write())
            await started.wait()
            release.set()
            confirmed = await wait_for(task, 5)
            await wait_for(writer, 5)
            assert confirmed is not None and len(confirmed.transactions) == 1
        async with factory() as checking:
            changed = await SqlAlchemyPortfolioProvider(checking).get_history_review(1, "AAA")
            assert changed is not None and len(changed.transactions) == 2
            assert changed.confirmed_at is None
            assert changed.history_gaps == (HoldingHistoryGap.HISTORY_CHANGED,)
    finally:
        release.set()
        await engine.dispose()



@pytest.mark.parametrize("status", [ImportStatus.PENDING, ImportStatus.RUNNING, ImportStatus.FAILED])
async def test_unknown_import_scope_is_always_blocking(
    async_session: AsyncSession, status: ImportStatus,
) -> None:
    provider = await seed(async_session)
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(1, "robinhood_csv", "test.csv", "raw", "a" * 64, 1, True)
    row = await async_session.get(models.StatementImport, job.id)
    assert row is not None
    row.status = status
    await async_session.commit()
    review = await provider.get_history_review(1, "AAA")
    assert review is not None and HoldingHistoryGap.IMPORT_NOT_SUCCEEDED in review.blocking_gaps
    with pytest.raises(HistoryConfirmationConflict):
        await provider.confirm_history(1, "AAA", review.review_token)
    assert await provider.get_history_review(1, "AAA") == review
@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1")])
async def test_invalid_persisted_financial_facts_remain_reviewable_but_not_confirmable(
    async_session: AsyncSession, value: Decimal,
) -> None:
    provider = await seed(async_session)
    row = await async_session.scalar(select(models.Transaction))
    assert row is not None
    row.price = value
    await async_session.commit()
    review = await provider.get_history_review(1, "AAA")
    assert review is not None and HoldingHistoryGap.INVALID_LEDGER in review.blocking_gaps
    assert review.confirmed_at is None and len(review.transactions) == 1
    with pytest.raises(HistoryConfirmationConflict):
        await provider.confirm_history(1, "AAA", review.review_token)
async def test_failed_confirmation_commit_rolls_back_attestation(
    async_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = await seed(async_session)
    review = await provider.get_history_review(1, "AAA")
    assert review is not None
    commit = async_session.commit
    monkeypatch.setattr(async_session, "commit", AsyncMock(side_effect=RuntimeError("disk failure")))
    with pytest.raises(RuntimeError, match="disk failure"):
        await provider.confirm_history(1, "AAA", review.review_token)
    monkeypatch.setattr(async_session, "commit", commit)
    restored = await provider.get_history_review(1, "AAA")
    assert restored is not None and restored.confirmed_at is None
    assert restored.review_token == review.review_token

@pytest.mark.parametrize("origin", list(LedgerOrigin))
async def test_read_records_map_persisted_origin_without_guessing(
    async_session: AsyncSession, origin: LedgerOrigin,
) -> None:
    provider = await seed(async_session)
    row = await async_session.scalar(select(models.Transaction))
    assert row is not None
    row.history_origin = origin
    await async_session.commit()
    async_session.expunge_all()
    records = await provider.list_transaction_records(1)
    review = await provider.get_history_review(1, "AAA")
    assert review is not None and review.transactions == tuple(records)
    assert len(records) == 1 and records[0].history_origin is origin
    assert records[0].price == Decimal("100.0123")


def test_history_state_keeps_original_canonical_field_order() -> None:
    # Moving origin into the read base must not invalidate saved token hashes.
    assert tuple(HistoryTransactionState.model_fields) == (
        *Transaction.model_fields, "id", "portfolio_id", "history_origin",
        "import_job_id", "deleted_at",
    )
