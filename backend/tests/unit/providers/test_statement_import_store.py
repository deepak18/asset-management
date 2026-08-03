"""Tests for the local-disk blob store and the SQLAlchemy import-job store.

The blob store is exercised against a real temp directory (it is thin I/O, and the
path-traversal guard is only meaningful against a real filesystem). The job store
runs on in-memory SQLite like the other provider tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio.schemas import ImportStatus, StatementFormat
from app.providers.statement_import_store import SqlAlchemyStatementImportStore
from app.providers.statement_storage import StatementStorageError
from app.storage.local_disk import LocalDiskStatementStorage

# --- blob storage ---------------------------------------------------------


async def test_put_then_get_round_trips(tmp_path: Path) -> None:
    storage = LocalDiskStatementStorage(tmp_path)
    await storage.put("abc.raw", b"hello,world\n")
    assert await storage.get("abc.raw") == b"hello,world\n"


async def test_put_creates_missing_directories(tmp_path: Path) -> None:
    storage = LocalDiskStatementStorage(tmp_path / "nested" / "deeper")
    await storage.put("abc.raw", b"x")
    assert (tmp_path / "nested" / "deeper" / "abc.raw").read_bytes() == b"x"


async def test_missing_object_raises(tmp_path: Path) -> None:
    storage = LocalDiskStatementStorage(tmp_path)
    with pytest.raises(StatementStorageError):
        await storage.get("nope.raw")


@pytest.mark.parametrize("key", ["../escape.raw", "a/b.raw", "a\\b.raw", "..", ""])
async def test_traversal_keys_are_rejected(tmp_path: Path, key: str) -> None:
    """A key must never be able to write outside the configured base directory."""

    storage = LocalDiskStatementStorage(tmp_path)
    with pytest.raises(StatementStorageError):
        await storage.put(key, b"x")


async def test_no_partial_file_is_left_behind(tmp_path: Path) -> None:
    storage = LocalDiskStatementStorage(tmp_path)
    await storage.put("abc.raw", b"payload")
    # The temp file used for the atomic replace must not survive a successful write.
    assert [p.name for p in tmp_path.iterdir()] == ["abc.raw"]


# --- job store ------------------------------------------------------------


async def _new_job(store: SqlAlchemyStatementImportStore, checksum: str = "cafe") -> int:
    job = await store.create_job(
        portfolio_id=1,
        source_format=StatementFormat.ROBINHOOD_CSV.value,
        original_filename="rh.csv",
        storage_key="rh.raw",
        checksum=checksum,
        size_bytes=42,
    )
    return job.id


async def test_create_job_starts_pending(async_session: AsyncSession) -> None:
    store = SqlAlchemyStatementImportStore(async_session)
    job_id = await _new_job(store)

    job = await store.get_job(job_id)
    assert job is not None
    assert job.status is ImportStatus.PENDING
    assert job.processed_rows == 0
    assert job.tickers == ()
    assert job.warnings == ()


async def test_lifecycle_transitions_to_succeeded(async_session: AsyncSession) -> None:
    store = SqlAlchemyStatementImportStore(async_session)
    job_id = await _new_job(store)

    await store.mark_running(job_id, total_rows=3)
    await store.record_progress(job_id, 2)
    await store.mark_succeeded(job_id, 3, ["AAPL", "MSFT"], ["row 4: skipped ACH"])

    job = await store.get_job(job_id)
    assert job is not None
    assert job.status is ImportStatus.SUCCEEDED
    assert job.total_rows == 3
    assert job.created_transactions == 3
    assert job.tickers == ("AAPL", "MSFT")
    assert job.warnings == ("row 4: skipped ACH",)
    assert job.started_at is not None and job.finished_at is not None


async def test_mark_failed_records_reason(async_session: AsyncSession) -> None:
    store = SqlAlchemyStatementImportStore(async_session)
    job_id = await _new_job(store)

    await store.mark_failed(job_id, "boom")

    job = await store.get_job(job_id)
    assert job is not None
    assert job.status is ImportStatus.FAILED
    assert job.error == "boom"


async def test_find_completed_by_checksum_only_matches_succeeded(
    async_session: AsyncSession,
) -> None:
    store = SqlAlchemyStatementImportStore(async_session)
    job_id = await _new_job(store, checksum="deadbeef")

    # Still pending -> not a duplicate blocker yet.
    assert await store.find_completed_by_checksum(1, "deadbeef") is None

    await store.mark_succeeded(job_id, 1, ["AAPL"], [])
    found = await store.find_completed_by_checksum(1, "deadbeef")
    assert found is not None and found.id == job_id

    # Scoped per portfolio: the same bytes in another portfolio are not duplicates.
    assert await store.find_completed_by_checksum(2, "deadbeef") is None


async def test_list_jobs_is_newest_first(async_session: AsyncSession) -> None:
    store = SqlAlchemyStatementImportStore(async_session)
    first = await _new_job(store, checksum="a")
    second = await _new_job(store, checksum="b")

    jobs = await store.list_jobs(1)
    assert [j.id for j in jobs] == [second, first]


async def test_unknown_job_returns_none(async_session: AsyncSession) -> None:
    store = SqlAlchemyStatementImportStore(async_session)
    assert await store.get_job(999) is None
