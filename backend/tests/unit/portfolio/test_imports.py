"""Unit tests for the asynchronous statement-import pipeline.

Both boundaries are faked (an in-memory job store and an in-memory blob store), so
these tests isolate the orchestration: accept-then-process, batched inserts with
progress publication, duplicate detection, and terminal-state error recording.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.portfolio.imports import (
    DuplicateStatementError,
    StatementImportService,
    compute_checksum,
    storage_key_for,
)
from app.portfolio.schemas import (
    HoldingInfo,
    ImportStatus,
    PortfolioCreate,
    PortfolioSummary,
    StatementFormat,
    StatementImportStatus,
    Transaction,
)
from app.providers.statement_storage import StatementStorageError

_CSV_HEADER = (
    b"Activity Date,Process Date,Settle Date,Instrument,Description,"
    b"Trans Code,Quantity,Price,Amount\n"
)
_CSV = _CSV_HEADER + (
    b"01/02/2020,01/03/2020,01/06/2020,AAPL,Apple,Buy,10,$100.00,($1000.00)\n"
    b"03/04/2021,03/05/2021,03/08/2021,AAPL,Apple,Sell,4,$150.00,$600.00\n"
    b"06/02/2022,06/02/2022,06/02/2022,,ACH Deposit,ACH,,,$500.00\n"
)


class _MemoryStorage:
    """Structural StatementStorage backed by a dict."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise StatementStorageError(f"missing {key}")
        return self.objects[key]


class _MemoryJobStore:
    """Structural StatementImportStore backed by dicts; records progress calls."""

    def __init__(self) -> None:
        self.jobs: dict[int, StatementImportStatus] = {}
        self.progress_calls: list[int] = []
        self._next_id = 1

    async def create_job(
        self,
        portfolio_id: int,
        source_format: str,
        original_filename: str,
        storage_key: str,
        checksum: str,
        size_bytes: int,
    ) -> StatementImportStatus:
        job_id = self._next_id
        self._next_id += 1
        job = StatementImportStatus(
            id=job_id,
            portfolio_id=portfolio_id,
            status=ImportStatus.PENDING,
            source_format=StatementFormat(source_format),
            original_filename=original_filename,
            checksum=checksum,
            size_bytes=size_bytes,
            created_at=datetime.now(UTC),
        )
        self.jobs[job_id] = job
        return job

    async def get_job(self, job_id: int) -> StatementImportStatus | None:
        return self.jobs.get(job_id)

    async def list_jobs(self, portfolio_id: int) -> list[StatementImportStatus]:
        return [j for j in self.jobs.values() if j.portfolio_id == portfolio_id]

    async def find_completed_by_checksum(
        self, portfolio_id: int, checksum: str
    ) -> StatementImportStatus | None:
        for job in self.jobs.values():
            if (
                job.portfolio_id == portfolio_id
                and job.checksum == checksum
                and job.status is ImportStatus.SUCCEEDED
            ):
                return job
        return None

    def _update(self, job_id: int, **fields: object) -> None:
        if job_id in self.jobs:
            self.jobs[job_id] = self.jobs[job_id].model_copy(update=fields)

    async def mark_running(self, job_id: int, total_rows: int | None = None) -> None:
        self._update(
            job_id,
            status=ImportStatus.RUNNING,
            started_at=datetime.now(UTC),
            total_rows=total_rows,
        )

    async def record_progress(self, job_id: int, processed_rows: int) -> None:
        self.progress_calls.append(processed_rows)
        self._update(job_id, processed_rows=processed_rows)

    async def mark_succeeded(
        self,
        job_id: int,
        created_transactions: int,
        tickers: list[str],
        warnings: list[str],
    ) -> None:
        self._update(
            job_id,
            status=ImportStatus.SUCCEEDED,
            finished_at=datetime.now(UTC),
            created_transactions=created_transactions,
            tickers=tuple(tickers),
            warnings=tuple(warnings),
        )

    async def mark_failed(self, job_id: int, error: str) -> None:
        self._update(
            job_id,
            status=ImportStatus.FAILED,
            finished_at=datetime.now(UTC),
            error=error,
        )


class _FakePortfolio:
    """Structural PortfolioProvider + PortfolioWriter."""

    def __init__(self, exists: bool = True) -> None:
        self.exists = exists
        self.transactions: list[Transaction] = []
        self.holdings: dict[str, HoldingInfo] = {}

    async def get_portfolio(self, portfolio_id: int) -> PortfolioSummary | None:
        if not self.exists:
            return None
        return PortfolioSummary(id=portfolio_id, name="M", base_currency="USD")

    async def list_portfolios(self) -> list[PortfolioSummary]:
        return []

    async def list_transactions(self, portfolio_id: int) -> list[Transaction]:
        return list(self.transactions)

    async def list_holdings(self, portfolio_id: int) -> list[HoldingInfo]:
        return list(self.holdings.values())

    async def create_portfolio(self, data: PortfolioCreate) -> PortfolioSummary:
        return PortfolioSummary(id=1, name=data.name, base_currency=data.base_currency)

    async def add_transactions(self, portfolio_id: int, transactions: object) -> int:
        rows = list(transactions)  # type: ignore[call-overload]
        self.transactions.extend(rows)
        return len(rows)

    async def upsert_holding(
        self,
        portfolio_id: int,
        ticker: str,
        sector: str | None = None,
        industry: str | None = None,
    ) -> None:
        self.holdings[ticker] = HoldingInfo(
            ticker=ticker, sector=sector, industry=industry
        )


def _build(
    batch_size: int = 500, exists: bool = True
) -> tuple[StatementImportService, _MemoryJobStore, _MemoryStorage, _FakePortfolio]:
    store, storage, portfolio = _MemoryJobStore(), _MemoryStorage(), _FakePortfolio(exists)
    service = StatementImportService(
        store=store,
        storage=storage,
        reader=portfolio,
        writer=portfolio,
        batch_size=batch_size,
    )
    return service, store, storage, portfolio


async def test_submit_stores_bytes_and_returns_pending_job() -> None:
    service, _store, storage, _p = _build()

    job = await service.submit(1, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV)

    assert job is not None
    assert job.status is ImportStatus.PENDING
    assert job.created_transactions == 0  # nothing processed yet
    assert job.checksum == compute_checksum(_CSV)
    assert job.size_bytes == len(_CSV)
    # Raw bytes went to the blob store under a content-derived key.
    key = storage_key_for(job.checksum, StatementFormat.ROBINHOOD_CSV)
    assert storage.objects[key] == _CSV


async def test_process_imports_and_reaches_succeeded() -> None:
    service, store, _storage, portfolio = _build()
    job = await service.submit(1, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV)
    assert job is not None

    await service.process(job.id, storage_key_for(job.checksum, job.source_format), 1)

    final = await store.get_job(job.id)
    assert final is not None
    assert final.status is ImportStatus.SUCCEEDED
    assert final.created_transactions == 2  # buy + sell (ACH skipped)
    assert final.total_rows == 2
    assert final.tickers == ("AAPL",)
    assert any("cash transfer" in w.lower() for w in final.warnings)
    assert len(portfolio.transactions) == 2
    assert "AAPL" in portfolio.holdings


async def test_progress_is_published_per_batch() -> None:
    """A small batch size must yield incremental progress, not one final jump."""

    service, store, _storage, _p = _build(batch_size=1)
    job = await service.submit(1, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV)
    assert job is not None

    await service.process(job.id, storage_key_for(job.checksum, job.source_format), 1)

    assert store.progress_calls == [1, 2]  # observable movement while running


async def test_duplicate_upload_is_rejected() -> None:
    service, _store, _storage, _p = _build()
    job = await service.submit(1, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV)
    assert job is not None
    await service.process(job.id, storage_key_for(job.checksum, job.source_format), 1)

    with pytest.raises(DuplicateStatementError):
        await service.submit(1, StatementFormat.ROBINHOOD_CSV, "rh-again.csv", _CSV)


async def test_duplicate_can_be_overridden_explicitly() -> None:
    service, _store, _storage, _p = _build()
    job = await service.submit(1, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV)
    assert job is not None
    await service.process(job.id, storage_key_for(job.checksum, job.source_format), 1)

    again = await service.submit(
        1, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV, allow_duplicate=True
    )
    assert again is not None


async def test_submit_missing_portfolio_returns_none() -> None:
    service, _store, _storage, _p = _build(exists=False)
    assert await service.submit(9, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV) is None


async def test_process_records_failure_instead_of_raising() -> None:
    """A detached job must never raise — its outcome has to land on the record."""

    service, store, _storage, _p = _build()
    job = await service.submit(1, StatementFormat.ROBINHOOD_CSV, "rh.csv", _CSV)
    assert job is not None

    await service.process(job.id, "no-such-key", 1)  # blob missing

    final = await store.get_job(job.id)
    assert final is not None
    assert final.status is ImportStatus.FAILED
    assert final.error is not None

