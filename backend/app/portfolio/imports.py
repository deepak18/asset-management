"""Asynchronous broker-statement import: accept fast, process in the background.

Why this is not a synchronous request
-------------------------------------
A ten-year activity export can hold thousands of rows. Parsing it, inserting every
transaction, and reconciling holdings inside the upload request would hold an HTTP
connection open for the whole job, risk proxy/browser timeouts, and give the user a
spinner with no information. So the upload path is split:

1. **Accept** (fast, synchronous): validate, checksum, persist the raw bytes, create
   a ``PENDING`` job row, return ``202 Accepted`` with the job id.
2. **Process** (background): parse, insert in batches, publish progress, finish in a
   terminal state (``SUCCEEDED``/``FAILED``).
3. **Poll**: the client reads the job until it reaches a terminal state, then
   refetches analytics.

Design choices worth stating
----------------------------
* **Job state lives in the database, not memory.** Progress must be readable by a
  *different* request (the poll) than the one that started the work, and it must
  survive the originating request finishing. Memory would fail both.
* **Batched inserts.** Rows are committed in configurable batches so a huge file
  never sits in one long-running transaction, and so ``processed_rows`` actually
  advances while the client watches.
* **Duplicate protection.** Re-uploading the same file would silently double every
  position. We detect identical content by SHA-256 and refuse unless explicitly
  overridden — a wrong ledger is far worse than an inconvenient error.
* **Trade-off, stated plainly:** execution uses in-process background tasks, which
  suits a single-user local workstation. They do not survive a process restart — an
  interrupted job stays visibly ``RUNNING`` rather than silently vanishing, because
  state is in the database. Moving to a durable worker (arq/Celery/RQ) later means
  replacing the runner only; the job model, storage, and API contract stay put.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from app.portfolio.schemas import (
    StatementFormat,
    StatementImportStatus,
    Transaction,
)
from app.portfolio.statements import StatementParseError, get_parser
from app.providers.base import (
    PortfolioProvider,
    PortfolioWriter,
    StatementImportStore,
)
from app.providers.statement_storage import StatementStorage, StatementStorageError


class DuplicateStatementError(ValueError):
    """Raised when identical statement bytes were already imported successfully."""

    def __init__(self, existing: StatementImportStatus) -> None:
        super().__init__(
            f"This file was already imported (job {existing.id}) and would "
            f"duplicate {existing.created_transactions} transactions."
        )
        self.existing = existing


def compute_checksum(data: bytes) -> str:
    """SHA-256 of the uploaded bytes — the content address and duplicate key."""

    return hashlib.sha256(data).hexdigest()


def storage_key_for(checksum: str, source_format: StatementFormat) -> str:
    """Build a flat, filesystem-safe storage key from content, not user input.

    Deriving the key from the checksum (never the uploaded filename) means a
    hostile or merely awkward filename can't influence where bytes land.
    """

    return f"{source_format.value}-{checksum}.raw"


class StatementImportService:
    """Accept statement uploads and run them to completion in the background."""

    def __init__(
        self,
        store: StatementImportStore,
        storage: StatementStorage,
        reader: PortfolioProvider,
        writer: PortfolioWriter,
        batch_size: int = 500,
        max_stored_warnings: int = 500,
    ) -> None:
        self._store = store
        self._storage = storage
        self._reader = reader
        self._writer = writer
        self._batch_size = max(1, batch_size)
        self._max_warnings = max(0, max_stored_warnings)

    async def submit(
        self,
        portfolio_id: int,
        source_format: StatementFormat,
        original_filename: str,
        data: bytes,
        allow_duplicate: bool = False,
    ) -> StatementImportStatus | None:
        """Store the upload and queue it. ``None`` if the portfolio doesn't exist.

        Raises :class:`DuplicateStatementError` when identical bytes already
        imported successfully into this portfolio, and
        :class:`~app.portfolio.statements.StatementParseError` when the payload
        obviously isn't a statement of the requested format. Both are cheap,
        *pre-acceptance* checks — we fail before creating a job so the user gets an
        immediate, actionable error instead of a job that fails a second later.
        """

        if await self._reader.get_portfolio(portfolio_id) is None:
            return None

        if not data:
            raise StatementParseError("uploaded file is empty")

        checksum = compute_checksum(data)
        if not allow_duplicate:
            existing = await self._store.find_completed_by_checksum(portfolio_id, checksum)
            if existing is not None:
                raise DuplicateStatementError(existing)

        # Validate the format up front (cheap header check) so an obviously wrong
        # file is rejected at upload time rather than surfacing as a failed job.
        parser = get_parser(source_format)
        parser.parse(data)

        key = storage_key_for(checksum, source_format)
        await self._storage.put(key, data)

        return await self._store.create_job(
            portfolio_id=portfolio_id,
            source_format=source_format.value,
            original_filename=original_filename,
            storage_key=key,
            checksum=checksum,
            size_bytes=len(data),
        )

    async def process(self, job_id: int, storage_key: str, portfolio_id: int) -> None:
        """Run one queued import to a terminal state.

        Never raises: this executes detached from any request, so a failure must be
        *recorded* on the job (where the user can see it), not propagated into a
        background-task handler that would swallow it.
        """

        try:
            data = await self._storage.get(storage_key)
            job = await self._store.get_job(job_id)
            if job is None:
                return

            parser = get_parser(StatementFormat(job.source_format))
            parsed = parser.parse(data)
            transactions = list(parsed.transactions)

            await self._store.mark_running(job_id, total_rows=len(transactions))
            created, tickers = await self._insert_in_batches(
                job_id, portfolio_id, transactions
            )

            await self._store.mark_succeeded(
                job_id,
                created_transactions=created,
                tickers=tickers,
                warnings=list(parsed.warnings)[: self._max_warnings],
            )
        except (StatementParseError, StatementStorageError) as exc:
            await self._store.mark_failed(job_id, str(exc))
        except Exception as exc:  # noqa: BLE001 - must not lose the job's outcome
            await self._store.mark_failed(job_id, f"unexpected error: {exc}")

    async def _insert_in_batches(
        self,
        job_id: int,
        portfolio_id: int,
        transactions: Sequence[Transaction],
    ) -> tuple[int, list[str]]:
        """Insert transactions in committed batches, publishing progress as we go."""

        created = 0
        classification: dict[str, tuple[str | None, str | None]] = {}

        for start in range(0, len(transactions), self._batch_size):
            batch = transactions[start : start + self._batch_size]
            created += await self._writer.add_transactions(portfolio_id, batch)
            for txn in batch:
                prev = classification.get(txn.ticker, (None, None))
                classification[txn.ticker] = (
                    txn.sector or prev[0],
                    txn.industry or prev[1],
                )
            await self._store.record_progress(job_id, created)

        # Ensure every touched ticker is a tracked holding so it shows up in the
        # holdings/allocation views. Done once at the end rather than per batch:
        # it is idempotent, and repeating it per batch would be wasted writes.
        for ticker, (sector, industry) in classification.items():
            await self._writer.upsert_holding(portfolio_id, ticker, sector, industry)

        return created, sorted(classification)


__all__ = [
    "DuplicateStatementError",
    "StatementImportService",
    "compute_checksum",
    "storage_key_for",
]
