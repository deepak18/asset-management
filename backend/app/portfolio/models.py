"""SQLAlchemy 2.0 mapped models for the portfolio domain.

Currency-aware ledger (PLAN.md §1.2 / decision #8): every ``Transaction`` carries
its own ``currency``, and each ``Portfolio`` declares a ``base_currency`` that the
calculators normalize to via the FX seam.

Money precision
---------------
Columns that hold money/quantities use an **exact decimal** type, never float.
On PostgreSQL that is native ``NUMERIC``. SQLite has no real decimal type and would
silently round-trip through binary float, corrupting values like ``0.012`` — so for
the SQLite dialect we swap in a ``TypeDecorator`` that stores the value as TEXT and
rebuilds an exact ``Decimal`` on read. ``.with_variant()`` picks the right one per
dialect, so unit tests (SQLite) and production (Postgres) are both exact.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.portfolio.schemas import TransactionType


class _SqliteDecimal(TypeDecorator[Decimal]):
    """Store a ``Decimal`` losslessly as TEXT on SQLite (which lacks a decimal type)."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(value)


# Exact decimal: native NUMERIC on Postgres, TEXT-backed Decimal on SQLite.
ExactDecimal = Numeric(28, 10).with_variant(_SqliteDecimal(), "sqlite")


class Portfolio(Base):
    """A single tracked portfolio with its reporting base currency."""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    base_currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Holding(Base):
    """A security position tracked in a portfolio, carrying classification metadata.

    Sector/industry live here (on the security), not on each transaction — they are
    the grouping keys for allocation roll-ups. One row per (portfolio, ticker).
    """

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("portfolio_id", "ticker", name="uq_holding_ticker"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    ticker: Mapped[str] = mapped_column(String(20))
    sector: Mapped[str | None] = mapped_column(String(80), default=None)
    industry: Mapped[str | None] = mapped_column(String(80), default=None)


class Transaction(Base):
    """A single dated ledger event (BUY/SELL/DIVIDEND/FEE/SPLIT) in native currency."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    ticker: Mapped[str] = mapped_column(String(20))
    type: Mapped[TransactionType] = mapped_column(SAEnum(TransactionType, name="transaction_type"))
    trade_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))

    quantity: Mapped[Decimal] = mapped_column(ExactDecimal, default=Decimal(0))
    price: Mapped[Decimal] = mapped_column(ExactDecimal, default=Decimal(0))
    fees: Mapped[Decimal] = mapped_column(ExactDecimal, default=Decimal(0))
    amount: Mapped[Decimal] = mapped_column(ExactDecimal, default=Decimal(0))
    split_ratio: Mapped[Decimal] = mapped_column(ExactDecimal, default=Decimal(1))


class Cash(Base):
    """A cash balance held in a portfolio, one row per currency."""

    __tablename__ = "cash_balances"
    __table_args__ = (UniqueConstraint("portfolio_id", "currency", name="uq_cash_currency"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    currency: Mapped[str] = mapped_column(String(3))
    balance: Mapped[Decimal] = mapped_column(ExactDecimal, default=Decimal(0))


class StatementImport(Base):
    """Metadata + progress for one uploaded broker statement.

    Only *metadata* lives here — the raw bytes are written to the blob store and
    referenced by ``storage_key``. Keeping large opaque files out of the database
    keeps backups small and lets the two halves scale independently.

    Persisting job state in the database (rather than in process memory) is what
    makes the pipeline honest across restarts: an interrupted job is still visibly
    ``RUNNING`` and can be inspected or re-driven, instead of vanishing silently.

    ``checksum`` is the SHA-256 of the uploaded bytes. It gives us content-addressed
    storage keys and, more importantly, lets us detect a re-upload of the same file
    — re-importing a decade of trades would silently double every position.
    """

    __tablename__ = "statement_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    source_format: Mapped[str] = mapped_column(String(40))

    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(120))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    total_rows: Mapped[int | None] = mapped_column(Integer, default=None)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_transactions: Mapped[int] = mapped_column(Integer, default=0)
    # Small JSON arrays kept as TEXT so the schema stays dialect-portable across
    # SQLite (tests) and PostgreSQL (production); they are read whole, never queried.
    tickers_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str | None] = mapped_column(Text, default=None)

