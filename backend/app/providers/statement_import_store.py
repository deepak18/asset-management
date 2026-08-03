"""SQLAlchemy-backed store for statement-import jobs.

Pure translation again: ORM rows in, typed :class:`StatementImportStatus` objects
out. The only wrinkle is the two small JSON arrays (tickers, warnings), which are
stored as TEXT for dialect portability and decoded here so no untyped structure
ever escapes the provider boundary.

Every mutator commits on its own. That is deliberate: a background job publishes
progress *while it runs*, and a client polling the status endpoint reads through a
different session — uncommitted progress would be invisible.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio import models
from app.portfolio.schemas import ImportStatus, StatementFormat, StatementImportStatus


def _decode_str_list(raw: str) -> tuple[str, ...]:
    """Decode a stored JSON array into a tuple of strings, tolerating corruption.

    A malformed blob must not make an otherwise-valid job unreadable, so we degrade
    to an empty list rather than raising while rendering status.
    """

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed)


def _to_status(row: models.StatementImport) -> StatementImportStatus:
    return StatementImportStatus(
        id=row.id,
        portfolio_id=row.portfolio_id,
        status=ImportStatus(row.status),
        source_format=StatementFormat(row.source_format),
        original_filename=row.original_filename,
        checksum=row.checksum,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        total_rows=row.total_rows,
        processed_rows=row.processed_rows,
        created_transactions=row.created_transactions,
        tickers=_decode_str_list(row.tickers_json),
        warnings=_decode_str_list(row.warnings_json),
        error=row.error,
    )


class SqlAlchemyStatementImportStore:
    """Persist import-job metadata and progress via an injected async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(
        self,
        portfolio_id: int,
        source_format: str,
        original_filename: str,
        storage_key: str,
        checksum: str,
        size_bytes: int,
    ) -> StatementImportStatus:
        row = models.StatementImport(
            portfolio_id=portfolio_id,
            status=ImportStatus.PENDING.value,
            source_format=source_format,
            original_filename=original_filename,
            storage_key=storage_key,
            checksum=checksum,
            size_bytes=size_bytes,
            created_at=datetime.now(UTC),
            processed_rows=0,
            created_transactions=0,
            tickers_json="[]",
            warnings_json="[]",
        )
        self._session.add(row)
        await self._session.commit()
        return _to_status(row)

    async def get_job(self, job_id: int) -> StatementImportStatus | None:
        row = await self._session.get(models.StatementImport, job_id)
        return None if row is None else _to_status(row)

    async def get_storage_key(self, job_id: int) -> str | None:
        """Return where a job's raw bytes live (used by the background processor)."""

        row = await self._session.get(models.StatementImport, job_id)
        return None if row is None else row.storage_key

    async def list_jobs(self, portfolio_id: int) -> list[StatementImportStatus]:
        stmt = (
            select(models.StatementImport)
            .where(models.StatementImport.portfolio_id == portfolio_id)
            .order_by(models.StatementImport.id.desc())
        )
        rows = (await self._session.scalars(stmt)).all()
        return [_to_status(row) for row in rows]

    async def find_completed_by_checksum(
        self, portfolio_id: int, checksum: str
    ) -> StatementImportStatus | None:
        stmt = (
            select(models.StatementImport)
            .where(
                models.StatementImport.portfolio_id == portfolio_id,
                models.StatementImport.checksum == checksum,
                models.StatementImport.status == ImportStatus.SUCCEEDED.value,
            )
            .order_by(models.StatementImport.id.desc())
        )
        row = (await self._session.scalars(stmt)).first()
        return None if row is None else _to_status(row)

    async def mark_running(self, job_id: int, total_rows: int | None = None) -> None:
        row = await self._session.get(models.StatementImport, job_id)
        if row is None:
            return
        row.status = ImportStatus.RUNNING.value
        row.started_at = datetime.now(UTC)
        row.total_rows = total_rows
        await self._session.commit()

    async def record_progress(self, job_id: int, processed_rows: int) -> None:
        row = await self._session.get(models.StatementImport, job_id)
        if row is None:
            return
        row.processed_rows = processed_rows
        await self._session.commit()

    async def mark_succeeded(
        self,
        job_id: int,
        created_transactions: int,
        tickers: list[str],
        warnings: list[str],
    ) -> None:
        row = await self._session.get(models.StatementImport, job_id)
        if row is None:
            return
        row.status = ImportStatus.SUCCEEDED.value
        row.finished_at = datetime.now(UTC)
        row.created_transactions = created_transactions
        row.tickers_json = json.dumps(tickers)
        row.warnings_json = json.dumps(warnings)
        await self._session.commit()

    async def mark_failed(self, job_id: int, error: str) -> None:
        row = await self._session.get(models.StatementImport, job_id)
        if row is None:
            return
        row.status = ImportStatus.FAILED.value
        row.finished_at = datetime.now(UTC)
        row.error = error
        await self._session.commit()
