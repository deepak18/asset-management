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
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio import models
from app.portfolio.schemas import (
    ImportIssue,
    ImportStatus,
    LedgerOrigin,
    SnapshotTransaction,
    StatementFormat,
    StatementImportStatus,
    Transaction,
    UnresolvedItem,
)


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
        history_complete=row.history_complete,
        retry_safe=row.retry_safe,
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
        history_complete: bool = False,
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
            history_complete=history_complete,
            retry_safe=True,
        )
        self._session.add(row)
        await self._session.commit()
        return _to_status(row)

    async def get_job(self, job_id: int) -> StatementImportStatus | None:
        row = await self._session.get(models.StatementImport, job_id)
        if row is None:
            return None
        issues = await self._session.scalars(
            select(models.ImportUnresolvedItem)
            .where(models.ImportUnresolvedItem.import_id == job_id)
            .order_by(models.ImportUnresolvedItem.id)
        )
        return _to_status(row).model_copy(
            update={"unresolved_items": tuple(_to_item(item) for item in issues)}
        )

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
        result: list[StatementImportStatus] = []
        for row in rows:
            job = await self.get_job(row.id)
            if job is not None:
                result.append(job)
        return result

    async def find_completed_by_checksum(
        self, portfolio_id: int, checksum: str
    ) -> StatementImportStatus | None:
        stmt = (
            select(models.StatementImport)
            .where(
                models.StatementImport.portfolio_id == portfolio_id,
                models.StatementImport.checksum == checksum,
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
        unresolved_items: Sequence[ImportIssue] = (),
    ) -> None:
        row = await self._session.get(models.StatementImport, job_id)
        if row is None:
            return
        row.status = ImportStatus.SUCCEEDED.value
        row.finished_at = datetime.now(UTC)
        row.created_transactions = created_transactions
        row.tickers_json = json.dumps(tickers)
        row.warnings_json = json.dumps(warnings)
        for issue in unresolved_items:
            self._session.add(
                models.ImportUnresolvedItem(
                    import_id=job_id,
                    portfolio_id=row.portfolio_id,
                    ticker=issue.ticker,
                    source_line=issue.source_line,
                    payload_json=issue.model_dump_json(),
                    resolved=False,
                )
            )
            if issue.ticker:
                await self._ensure_holding(row.portfolio_id, issue.ticker)
        await self._session.commit()

    async def mark_failed(self, job_id: int, error: str) -> None:
        await self._session.rollback()
        row = await self._session.get(models.StatementImport, job_id)
        if row is None:
            return
        row.status = ImportStatus.FAILED.value
        row.finished_at = datetime.now(UTC)
        row.error = error
        await self._session.commit()

    async def claim_job(self, job_id: int) -> bool:
        result = await self._session.execute(
            update(models.StatementImport)
            .where(
                models.StatementImport.id == job_id,
                models.StatementImport.status == ImportStatus.PENDING.value,
            )
            .values(status=ImportStatus.RUNNING.value, started_at=datetime.now(UTC))
            .returning(models.StatementImport.id)
        )
        claimed = result.scalar_one_or_none() is not None
        await self._session.commit()
        return claimed

    async def _ensure_holding(self, portfolio_id: int, ticker: str) -> None:
        existing = await self._session.scalar(
            select(models.Holding).where(
                models.Holding.portfolio_id == portfolio_id,
                models.Holding.ticker == ticker,
            )
        )
        if existing is None:
            self._session.add(models.Holding(portfolio_id=portfolio_id, ticker=ticker))
            await self._session.flush()

    async def append_batch(self, job_id: int, transactions: Sequence[Transaction]) -> int:
        job = await self._session.get(models.StatementImport, job_id)
        if job is None or job.status != ImportStatus.RUNNING.value:
            raise ValueError("import is not running")
        for txn in transactions:
            self._session.add(_event_row(job.portfolio_id, txn, job_id))
            await self._ensure_holding(job.portfolio_id, txn.ticker)
        job.processed_rows += len(transactions)
        job.created_transactions += len(transactions)
        await self._session.commit()
        return len(transactions)

    async def reconcile_interrupted(self) -> int:
        result = await self._session.execute(
            update(models.StatementImport)
            .where(
                models.StatementImport.status.in_(
                    [ImportStatus.PENDING.value, ImportStatus.RUNNING.value]
                ),
            )
            .values(
                status=ImportStatus.FAILED.value,
                finished_at=datetime.now(UTC),
                error="Import interrupted by application restart; retry from stored bytes.",
            )
            .returning(models.StatementImport.id)
        )
        count = len(result.scalars().all())
        await self._session.commit()
        return count

    async def reset_failed(self, portfolio_id: int, job_id: int) -> StatementImportStatus | None:
        result = await self._session.execute(
            update(models.StatementImport)
            .where(
                models.StatementImport.id == job_id,
                models.StatementImport.portfolio_id == portfolio_id,
                models.StatementImport.status == ImportStatus.FAILED.value,
                models.StatementImport.retry_safe.is_(True),
                ~select(models.Transaction.id).where(
                    models.Transaction.import_job_id == job_id,
                    models.Transaction.deleted_at.is_not(None),
                ).exists(),
            )
            .values(
                status=ImportStatus.PENDING.value,
                started_at=None,
                finished_at=None,
                total_rows=None,
                processed_rows=0,
                created_transactions=0,
                tickers_json="[]",
                warnings_json="[]",
                error=None,
            )
            .returning(models.StatementImport.id)
        )
        if result.scalar_one_or_none() is None:
            await self._session.rollback()
            job = await self.get_job(job_id)
            if job is None or job.portfolio_id != portfolio_id:
                return None
            raise ValueError(
                "Only FAILED, ownership-tracked imports without deleted events can be retried; "
                "legacy or user-edited imports require manual reconciliation"
            )
        await self._session.execute(
            delete(models.Transaction).where(models.Transaction.import_job_id == job_id)
        )
        await self._session.execute(
            delete(models.ImportUnresolvedItem).where(
                models.ImportUnresolvedItem.import_id == job_id
            )
        )
        await self._session.commit()
        return await self.get_job(job_id)

    async def list_unresolved(
        self, portfolio_id: int, include_resolved: bool = False
    ) -> list[UnresolvedItem]:
        stmt = (
            select(models.ImportUnresolvedItem)
            .join(models.StatementImport)
            .where(
                models.ImportUnresolvedItem.portfolio_id == portfolio_id,
                models.StatementImport.status == ImportStatus.SUCCEEDED.value,
            )
            .order_by(models.ImportUnresolvedItem.id)
        )
        if not include_resolved:
            stmt = stmt.where(models.ImportUnresolvedItem.resolved.is_(False))
        return [_to_item(row) for row in await self._session.scalars(stmt)]

    async def resolve_item(
        self, portfolio_id: int, item_id: int, transaction: Transaction
    ) -> UnresolvedItem | None:
        result = await self._session.execute(
            update(models.ImportUnresolvedItem)
            .where(
                models.ImportUnresolvedItem.id == item_id,
                models.ImportUnresolvedItem.portfolio_id == portfolio_id,
                models.ImportUnresolvedItem.resolved.is_(False),
            )
            .values(resolved=True)
            .returning(models.ImportUnresolvedItem.id)
        )
        if result.scalar_one_or_none() is None:
            await self._session.rollback()
            row = await self._session.get(models.ImportUnresolvedItem, item_id)
            if row is None or row.portfolio_id != portfolio_id:
                return None
            raise ValueError("Item is already resolved")
        # Corrections are independent user entries, never deleted by retry cleanup.
        self._session.add(_event_row(portfolio_id, transaction, None))
        await self._ensure_holding(portfolio_id, transaction.ticker)
        await self._session.commit()
        row = await self._session.get(models.ImportUnresolvedItem, item_id)
        assert row is not None
        return _to_item(row)


def _to_item(row: models.ImportUnresolvedItem) -> UnresolvedItem:
    issue = ImportIssue.model_validate_json(row.payload_json)
    return UnresolvedItem(
        **issue.model_dump(),
        id=row.id,
        import_id=row.import_id,
        portfolio_id=row.portfolio_id,
        resolved=row.resolved,
    )


def _event_row(portfolio_id: int, txn: Transaction, job_id: int | None) -> models.Transaction:
    return models.Transaction(
        portfolio_id=portfolio_id,
        ticker=txn.ticker,
        type=txn.type,
        trade_date=txn.trade_date,
        currency=txn.currency,
        quantity=txn.quantity,
        price=txn.price,
        amount=txn.amount,
        fees=txn.fees,
        split_ratio=txn.split_ratio,
        import_job_id=job_id,
        history_origin=(
            LedgerOrigin.SNAPSHOT if isinstance(txn, SnapshotTransaction)
            else LedgerOrigin.OBSERVED
        ).value,
    )
