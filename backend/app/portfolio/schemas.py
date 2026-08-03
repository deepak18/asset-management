"""Typed inputs/outputs for the portfolio calculators.

No ``dict`` or ``Any`` structural payloads: every transfer object is a Pydantic
model or an ``Enum``. These are pure data carriers — they contain no business
logic and no I/O.

Design rationale (the "why" behind the recurring choices here):

* ``Decimal`` for every money/quantity field. Binary ``float`` cannot represent
  values like ``0.1`` exactly, so ``0.1 + 0.2 != 0.3`` — unacceptable for a ledger.
  ``Decimal`` is exact base-10 arithmetic. (The only place we drop to ``float`` is
  inside the XIRR root-finder, which needs fractional exponentiation.)
* ``ConfigDict(frozen=True)`` makes every model immutable + hashable. A ``Transaction``
  or ``FxRate`` is a recorded *fact*; freezing it prevents "someone mutated the ledger
  mid-calculation" bugs and keeps the calculators referentially transparent.
* Separate **input** models (``Transaction``, ``CashFlow``) from **result** models
  (``CostBasisResult``, ``UnrealizedResult``, ``AllocationWeight``). Facts in →
  computed facts out, with no shared mutable state — this is what makes the
  calculators pure, trivially testable functions.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TransactionType(StrEnum):
    """Ledger event kinds supported by the deterministic calculators."""

    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    FEE = "FEE"
    SPLIT = "SPLIT"


class Transaction(BaseModel):
    """A single dated ledger event for one ticker, in its native currency.

    Field usage by ``type``:

    * ``BUY`` / ``SELL``: ``quantity`` (> 0) and ``price`` per share; ``fees`` optional.
    * ``DIVIDEND``: ``amount`` = total cash received (native currency).
    * ``FEE``: ``amount`` = total fee paid (native currency).
    * ``SPLIT``: ``split_ratio`` (e.g. ``2`` for a 2-for-1); other fields ignored.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1)
    type: TransactionType
    trade_date: date
    currency: str = Field(min_length=3, max_length=3)

    quantity: Decimal = Decimal(0)
    price: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)
    amount: Decimal = Decimal(0)
    split_ratio: Decimal = Decimal(1)
    # Optional grouping metadata for allocation (kept here so a Transaction can
    # seed a position without a second lookup). Never required by the math.
    sector: str | None = None
    industry: str | None = None


class PositionValue(BaseModel):
    """A holding's current market value, already normalized to the base currency."""

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1)
    market_value: Decimal
    sector: str | None = None
    industry: str | None = None


class PortfolioSummary(BaseModel):
    """Lightweight portfolio identity + reporting base currency (provider output)."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    base_currency: str = Field(min_length=3, max_length=3)


class HoldingInfo(BaseModel):
    """A tracked security's classification metadata (provider output).

    Grouping keys for allocation roll-ups; the market value is joined in later once
    the market-data layer (§1.3) can price the position.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1)
    sector: str | None = None
    industry: str | None = None


class AllocationWeight(BaseModel):
    """One row of an allocation breakdown."""

    model_config = ConfigDict(frozen=True)

    key: str
    market_value: Decimal
    weight: Decimal  # fraction in [0, 1]; sums to 1 across a non-empty breakdown


class OpenLot(BaseModel):
    """An unclosed FIFO purchase lot, valued in the portfolio base currency."""

    model_config = ConfigDict(frozen=True)

    trade_date: date
    quantity: Decimal
    cost_per_share_base: Decimal  # base-currency cost basis per share


class CostBasisResult(BaseModel):
    """Outcome of replaying a ticker's ledger under FIFO lot accounting."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    open_quantity: Decimal
    open_cost_basis_base: Decimal
    realized_pnl_base: Decimal
    dividends_base: Decimal
    fees_base: Decimal
    open_lots: tuple[OpenLot, ...]


class UnrealizedResult(BaseModel):
    """Mark-to-market of open lots against a current price."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    open_quantity: Decimal
    open_cost_basis_base: Decimal
    market_value_base: Decimal
    unrealized_pnl_base: Decimal


class CashFlow(BaseModel):
    """A dated signed cash flow (native currency) for money-weighted return math.

    Sign convention (investor's perspective):
    negative = money leaving the investor (buys, fees);
    positive = money returning to the investor (sells, dividends).
    """

    model_config = ConfigDict(frozen=True)

    date: date
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)


class PortfolioAnalytics(BaseModel):
    """Aggregated, base-currency portfolio analytics (the service layer's output).

    This is the single typed envelope the ``/analytics`` endpoint returns. It bundles
    the portfolio identity, per-position FIFO cost-basis results, whole-portfolio
    roll-up totals, and the money-weighted return (XIRR).

    ``money_weighted_return`` is ``None`` when XIRR is mathematically undefined
    (e.g. an empty ledger, or flows that never change sign) — we surface "not
    computable" honestly rather than emitting a misleading ``0``. It is a *rate*
    (annualized fraction), not money, but is kept as ``Decimal`` so no ``float``
    leaks into a financial payload.

    Market-value-dependent figures — per-position unrealized P&L and allocation
    weights — are populated when the market-data provider supplies current
    prices. When prices are unavailable (no provider configured, quota exhausted,
    or a missing FX rate) those fields degrade gracefully: totals are ``None``,
    allocation lists are empty, and the affected tickers are reported in
    ``unpriced_tickers`` so the omission is explicit, never a silent ``0``.
    """

    model_config = ConfigDict(frozen=True)

    portfolio: PortfolioSummary
    base_currency: str = Field(min_length=3, max_length=3)
    positions: tuple[CostBasisResult, ...]
    realized_pnl_base: Decimal
    dividends_base: Decimal
    fees_base: Decimal
    open_cost_basis_base: Decimal
    money_weighted_return: Decimal | None = None

    # Market-value-dependent analytics (present only when priced).
    positions_unrealized: tuple[UnrealizedResult, ...] = ()
    market_value_base: Decimal | None = None
    unrealized_pnl_base: Decimal | None = None
    allocation_by_ticker: tuple[AllocationWeight, ...] = ()
    allocation_by_sector: tuple[AllocationWeight, ...] = ()
    allocation_by_industry: tuple[AllocationWeight, ...] = ()
    unpriced_tickers: tuple[str, ...] = ()
    priced_as_of: datetime | None = None


# ---------------------------------------------------------------------------
# Write-side inputs (manual entry, snapshots, statement import)
# ---------------------------------------------------------------------------
#
# These are the request bodies the write endpoints accept. They stay separate
# from the read/result models above: an *input* describes what a user asserts,
# a *result* describes what the deterministic core computed. Keeping them apart
# is what lets the calculators remain pure functions of recorded facts.


class PortfolioCreate(BaseModel):
    """Request body to create a new (empty) portfolio."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=120)
    base_currency: str = Field(min_length=3, max_length=3)


class PositionSnapshot(BaseModel):
    """A user's *current* holding, captured without full transaction history.

    This is the answer to "my portfolio is 10 years old and I don't want to key in
    every trade": you assert the position as it stands today — how many shares you
    hold and what they cost — and the system records it as a single opening ``BUY``
    lot in the ledger. Every downstream calculator then treats it like any other
    lot, so cost-basis and unrealized P&L are exact.

    Provide the cost basis exactly one of two ways (brokerages report both):

    * ``cost_basis_per_share`` — the average price paid per share, or
    * ``total_cost_basis`` — the aggregate amount invested (we divide by quantity).

    ``as_of`` is the acquisition/opening date. When you genuinely don't know it,
    leave it unset and the service stamps today's date — but note the money-weighted
    return (XIRR) is only meaningful with a *real* purchase date, so a snapshot with
    a placeholder date will (correctly) leave XIRR undefined while cost-basis and
    unrealized P&L stay exact.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1, max_length=20)
    quantity: Decimal = Field(gt=Decimal(0))
    currency: str = Field(min_length=3, max_length=3)
    as_of: date | None = None
    cost_basis_per_share: Decimal | None = Field(default=None, ge=Decimal(0))
    total_cost_basis: Decimal | None = Field(default=None, ge=Decimal(0))
    sector: str | None = Field(default=None, max_length=80)
    industry: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _exactly_one_cost_basis(self) -> PositionSnapshot:
        """Require exactly one cost-basis form so the opening price is unambiguous."""

        provided = (self.cost_basis_per_share is not None) + (
            self.total_cost_basis is not None
        )
        if provided != 1:
            raise ValueError(
                "provide exactly one of 'cost_basis_per_share' or 'total_cost_basis'"
            )
        return self


class StatementFormat(StrEnum):
    """Supported broker statement layouts for the import endpoint."""

    ROBINHOOD_CSV = "robinhood_csv"


class ParsedStatement(BaseModel):
    """A broker statement decoded into ledger transactions + non-fatal warnings.

    The parser never silently drops information: rows it cannot map to a supported
    ledger event are surfaced in ``warnings`` (e.g. an unknown transaction code)
    rather than discarded without a trace.
    """

    model_config = ConfigDict(frozen=True)

    source_format: StatementFormat
    transactions: tuple[Transaction, ...]
    warnings: tuple[str, ...] = ()


class LedgerIngestResult(BaseModel):
    """What a write/import operation actually recorded (the endpoint's response)."""

    model_config = ConfigDict(frozen=True)

    portfolio_id: int
    created_transactions: int
    tickers: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    source_format: StatementFormat | None = None


class ImportStatus(StrEnum):
    """Lifecycle of an asynchronous statement import."""

    PENDING = "PENDING"      # accepted + stored, not yet picked up
    RUNNING = "RUNNING"      # actively parsing/inserting
    SUCCEEDED = "SUCCEEDED"  # finished; transactions are in the ledger
    FAILED = "FAILED"        # aborted; see `error`


class StatementImportStatus(BaseModel):
    """Progress + outcome of one statement import (what the UI polls).

    A decade-long export can hold thousands of rows, so the upload endpoint returns
    immediately with this record in ``PENDING`` and the work continues in the
    background. The client polls until ``status`` is terminal.

    ``processed_rows``/``total_rows`` drive a progress bar. ``total_rows`` is
    ``None`` until parsing has counted the file, because an honest "unknown" is
    better than a fake denominator that makes a progress bar jump backwards.
    """

    model_config = ConfigDict(frozen=True)

    id: int
    portfolio_id: int
    status: ImportStatus
    source_format: StatementFormat
    original_filename: str
    checksum: str
    size_bytes: int

    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    total_rows: int | None = None
    processed_rows: int = 0
    created_transactions: int = 0
    tickers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None
