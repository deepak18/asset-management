from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio import models
from app.portfolio.imports import StatementImportService, storage_key_for
from app.portfolio.schemas import (
    ImportStatus,
    PortfolioCreate,
    PositionSnapshot,
    StatementFormat,
    Transaction,
    TransactionType,
    UnresolvedResolution,
)
from app.providers.portfolio_provider import SqlAlchemyPortfolioProvider
from app.providers.statement_import_store import SqlAlchemyStatementImportStore
from app.providers.statement_storage import StatementStorageError
from app.storage.local_disk import LocalDiskStatementStorage

_CSV = (
    b"Activity Date,Instrument,Description,Trans Code,Quantity,Price,Amount\n"
    b"01/01/2020,AAPL,buy,Buy,10,$100,($1000)\n"
    b"01/02/2020,AAPL,buy,Buy,2,$100,($200)\n"
)


async def _setup(session: AsyncSession, tmp_path: Path):
    provider = SqlAlchemyPortfolioProvider(session)
    portfolio = await provider.create_portfolio(
        PortfolioCreate(name="Recovery", base_currency="USD")
    )
    store = SqlAlchemyStatementImportStore(session)
    storage = LocalDiskStatementStorage(tmp_path)
    service = StatementImportService(store, storage, provider, provider, batch_size=1)
    return portfolio.id, provider, store, storage, service


async def test_partial_failure_retry_never_duplicates_manual_or_imported_events(
    async_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid, provider, store, _storage, service = await _setup(async_session, tmp_path)
    manual = Transaction(
        ticker="AAPL",
        type=TransactionType.BUY,
        trade_date=date(2019, 1, 1),
        currency="USD",
        quantity=Decimal("1"),
        price=Decimal("50"),
    )
    await provider.add_transactions(pid, [manual])
    job = await service.submit(pid, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV)
    assert job is not None
    key = storage_key_for(job.checksum, job.source_format)
    real_append = store.append_batch
    calls = 0

    async def fail_second(job_id: int, transactions: Sequence[Transaction]) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated crash after first committed batch")
        return await real_append(job_id, transactions)

    monkeypatch.setattr(store, "append_batch", fail_second)
    await service.process(job.id, key, pid)
    failed = await store.get_job(job.id)
    assert failed is not None and failed.status == ImportStatus.FAILED
    assert failed.processed_rows == 1 and failed.created_transactions == 1
    assert len(await provider.list_transactions(pid)) == 2
    monkeypatch.setattr(store, "append_batch", real_append)
    queued = await service.retry(pid, job.id)
    assert queued is not None and queued.id == job.id and queued.status == ImportStatus.PENDING
    assert await provider.list_transactions(pid) == [manual]
    await service.process(job.id, key, pid)
    await service.process(job.id, key, pid)  # duplicate runner is harmless
    assert len(await provider.list_transactions(pid)) == 3
    done = await store.get_job(job.id)
    assert done is not None and done.status == ImportStatus.SUCCEEDED
    assert done.created_transactions == 2
    with pytest.raises(ValueError, match="FAILED"):
        await service.retry(pid, job.id)


async def test_startup_reconciliation_and_corrupt_bytes_refuse_cleanup(
    async_session: AsyncSession,
    tmp_path: Path,
) -> None:
    pid, provider, store, storage, service = await _setup(async_session, tmp_path)
    job = await service.submit(pid, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV)
    assert job is not None
    assert await store.claim_job(job.id)
    txn = Transaction(
        ticker="AAPL",
        type=TransactionType.BUY,
        trade_date=date(2020, 1, 1),
        currency="USD",
        quantity=Decimal("10"),
        price=Decimal("100"),
    )
    await store.append_batch(job.id, [txn])
    assert await store.reconcile_interrupted() == 1
    assert await store.reconcile_interrupted() == 0
    failed = await store.get_job(job.id)
    assert failed is not None and failed.status == ImportStatus.FAILED
    key = storage_key_for(job.checksum, job.source_format)
    await storage.put(key, b"corrupt")
    with pytest.raises(StatementStorageError, match="checksum"):
        await service.retry(pid, job.id)
    assert len(await provider.list_transactions(pid)) == 1
    await storage.put(key, _CSV)
    assert await service.retry(pid, job.id) is not None


async def test_unresolved_items_persist_and_resolution_is_exactly_once(
    async_session: AsyncSession,
    tmp_path: Path,
) -> None:
    pid, provider, store, _storage, service = await _setup(async_session, tmp_path)
    data = (
        b"Activity Date,Instrument,Description,Trans Code,Quantity,Price,Amount\n"
        b"01/01/2020,AAPL,incoming,ITRF,3,,\n"
    )
    job = await service.submit(pid, StatementFormat.ROBINHOOD_CSV, "rh.csv", data)
    assert job is not None
    await service.process(job.id, storage_key_for(job.checksum, job.source_format), pid)
    items = await store.list_unresolved(pid)
    assert len(items) == 1 and items[0].kind == "TRANSFER_IN_NO_COST_BASIS"
    # A fresh provider can read the persisted repair state, not process memory.
    fresh = SqlAlchemyStatementImportStore(async_session)
    polled = await fresh.get_job(job.id)
    assert polled is not None and polled.unresolved_items == tuple(items)
    holding = await provider.get_holding(pid, "AAPL")
    assert holding is not None and "COST_BASIS" in holding.data_gaps
    resolution = UnresolvedResolution(
        snapshot=PositionSnapshot(
            ticker="AAPL", quantity=Decimal("3"), currency="USD", total_cost_basis=Decimal("300")
        )
    )
    resolved = await service.resolve(pid, items[0].id, resolution)
    assert resolved is not None and resolved.resolved
    with pytest.raises(ValueError, match="already resolved"):
        await service.resolve(pid, items[0].id, resolution)
    assert len(await provider.list_transactions(pid)) == 1
    assert await store.list_unresolved(pid) == []
    holding = await provider.get_holding(pid, "AAPL")
    assert holding is not None and "COST_BASIS" not in holding.data_gaps


async def test_legacy_partial_import_cannot_be_retried(
    async_session: AsyncSession, tmp_path: Path
) -> None:
    pid, _provider, store, _storage, service = await _setup(async_session, tmp_path)
    job = await service.submit(pid, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV)
    assert job is not None
    await store.mark_failed(job.id, "legacy")
    row = await async_session.scalar(
        select(models.StatementImport).where(models.StatementImport.id == job.id)
    )
    assert row is not None
    row.retry_safe = False
    await async_session.commit()
    with pytest.raises(ValueError, match="legacy"):
        await service.retry(pid, job.id)
