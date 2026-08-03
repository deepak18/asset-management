"""Provider interfaces — the ONLY sanctioned I/O boundary.

Domain logic (the calculators) depends on these *interfaces*, never on SQLAlchemy
sessions, HTTP clients, or MCP packets. Concretely, a provider takes raw storage
and hands back **typed Pydantic domain objects** the calculators already understand.
This is what lets us swap Postgres, a mock, or a future service in without touching
a single line of financial math.

We use ``typing.Protocol`` (structural typing) rather than an ABC so implementations
don't need to inherit anything — a class "is" a ``PortfolioProvider`` simply by having
the right async methods. That keeps the boundary decoupled and easy to fake in tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.portfolio.schemas import (
    HoldingInfo,
    PortfolioCreate,
    PortfolioSummary,
    StatementImportStatus,
    Transaction,
)


class PortfolioProvider(Protocol):
    """Read access to a portfolio's ledger, holdings, and identity."""

    async def list_portfolios(self) -> list[PortfolioSummary]:
        """Return every tracked portfolio (the UI's portfolio picker feeds on this)."""
        ...

    async def get_portfolio(self, portfolio_id: int) -> PortfolioSummary | None:
        """Return the portfolio's identity/base currency, or ``None`` if absent."""
        ...

    async def list_transactions(self, portfolio_id: int) -> list[Transaction]:
        """Return all ledger events for the portfolio as typed domain objects."""
        ...

    async def list_holdings(self, portfolio_id: int) -> list[HoldingInfo]:
        """Return the portfolio's tracked securities + classification metadata."""
        ...


class PortfolioWriter(Protocol):
    """Write access to a portfolio's identity, ledger, and holding classification.

    Kept separate from :class:`PortfolioProvider` (interface segregation): read-only
    consumers — the analytics service, tests — never gain accidental write power, and
    a future read replica / cache can implement only the read half. A single concrete
    class may of course satisfy both Protocols.
    """

    async def create_portfolio(self, data: PortfolioCreate) -> PortfolioSummary:
        """Persist a new empty portfolio and return its assigned identity."""
        ...

    async def add_transactions(
        self, portfolio_id: int, transactions: Sequence[Transaction]
    ) -> int:
        """Append ledger events, returning how many were written."""
        ...

    async def upsert_holding(
        self,
        portfolio_id: int,
        ticker: str,
        sector: str | None = None,
        industry: str | None = None,
    ) -> None:
        """Create or update a holding's classification metadata (idempotent by ticker).

        Non-null ``sector``/``industry`` overwrite; ``None`` leaves an existing value
        intact so re-importing a bare ticker never erases classification you added.
        """
        ...


class StatementImportStore(Protocol):
    """Persistence for asynchronous statement-import jobs (metadata + progress).

    Job state is kept in the database rather than process memory so progress
    survives across the request that started it — and so an interrupted job stays
    visible instead of disappearing.
    """

    async def create_job(
        self,
        portfolio_id: int,
        source_format: str,
        original_filename: str,
        storage_key: str,
        checksum: str,
        size_bytes: int,
    ) -> StatementImportStatus:
        """Record a newly accepted upload in the ``PENDING`` state."""
        ...

    async def get_job(self, job_id: int) -> StatementImportStatus | None:
        """Return one job's current status, or ``None`` if it doesn't exist."""
        ...

    async def list_jobs(self, portfolio_id: int) -> list[StatementImportStatus]:
        """Return a portfolio's import history, newest first."""
        ...

    async def find_completed_by_checksum(
        self, portfolio_id: int, checksum: str
    ) -> StatementImportStatus | None:
        """Return a prior successful import of identical bytes, if any.

        Used to block accidental double-imports, which would duplicate every
        transaction in the file and corrupt cost basis.
        """
        ...

    async def mark_running(self, job_id: int, total_rows: int | None = None) -> None:
        """Transition a job to ``RUNNING`` and stamp its start time."""
        ...

    async def record_progress(self, job_id: int, processed_rows: int) -> None:
        """Publish incremental progress so a client polling the job sees movement."""
        ...

    async def mark_succeeded(
        self,
        job_id: int,
        created_transactions: int,
        tickers: list[str],
        warnings: list[str],
    ) -> None:
        """Transition a job to ``SUCCEEDED`` with its final counts + diagnostics."""
        ...

    async def mark_failed(self, job_id: int, error: str) -> None:
        """Transition a job to ``FAILED`` with a human-readable reason."""
        ...
