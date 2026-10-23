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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.marketdata.schemas import MarketDataProvenance


class LedgerOrigin(StrEnum):
    OBSERVED = "OBSERVED"
    SNAPSHOT = "SNAPSHOT"
    UNKNOWN = "UNKNOWN"


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

    model_config = ConfigDict(frozen=True, extra="forbid")

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


class TransactionRecord(Transaction):
    """Persisted ledger read; identity and origin are absent from write inputs."""

    # Legacy corrupt rows must remain reviewable, not become a server error.
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=True)

    id: int
    portfolio_id: int
    history_origin: LedgerOrigin


class HoldingHistoryGap(StrEnum):
    NO_TRANSACTIONS = "NO_TRANSACTIONS"
    NO_ACQUISITION = "NO_ACQUISITION"
    UNKNOWN_ORIGIN = "UNKNOWN_ORIGIN"
    SNAPSHOT = "SNAPSHOT"
    IMPORT_NOT_COMPLETE = "IMPORT_NOT_COMPLETE"
    IMPORT_NOT_SUCCEEDED = "IMPORT_NOT_SUCCEEDED"
    UNRESOLVED_EVENTS = "UNRESOLVED_EVENTS"
    DELETED_TRANSACTION = "DELETED_TRANSACTION"
    HISTORY_CHANGED = "HISTORY_CHANGED"
    INVALID_LEDGER = "INVALID_LEDGER"


class HoldingHistoryConfirmation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    review_token: str
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def _strict_acknowledgement(cls, value: object) -> object:
        if value is not True:
            raise ValueError("confirmed must be the boolean true")
        return value


class HoldingHistoryReview(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    history_complete: bool
    history_gaps: tuple[HoldingHistoryGap, ...]
    blocking_gaps: tuple[HoldingHistoryGap, ...]
    review_token: str
    confirmed_at: datetime | None
    transactions: tuple[TransactionRecord, ...]


class HistoryTransactionState(TransactionRecord):
    import_job_id: int | None
    deleted_at: datetime | None


class HistoryImportState(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: int
    portfolio_id: int
    status: ImportStatus
    history_complete: bool
    tickers: tuple[str, ...]
    unresolved_items: tuple[UnresolvedItem, ...]


class HoldingHistorySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    portfolio_id: int
    ticker: str
    transactions: tuple[HistoryTransactionState, ...]
    imports: tuple[HistoryImportState, ...]


class SnapshotTransaction(Transaction):
    """Internal marker; never accepted as a manual transaction request model."""


class HoldingReturnStatus(StrEnum):
    OK = "OK"
    INCOMPLETE_HISTORY = "INCOMPLETE_HISTORY"
    UNPRICED_POSITION = "UNPRICED_POSITION"
    MISSING_FX = "MISSING_FX"
    INSUFFICIENT_FLOWS = "INSUFFICIENT_FLOWS"
    INVALID_HISTORY = "INVALID_HISTORY"


class HoldingValuationSource(StrEnum):
    LEDGER = "LEDGER"
    QUOTE = "QUOTE"
    UNAVAILABLE = "UNAVAILABLE"


class HoldingAnalytics(BaseModel):
    """Ticker-only annualized XIRR; unavailable returns are null, never synthetic zero.

    Open positions use valuation_date as the terminal-flow/FX date, with the
    last-known quote's own source timestamp preserved in valuation_provenance.
    Closed positions use the final ledger date and need no external valuation.
    """

    model_config = ConfigDict(frozen=True)
    portfolio_id: int
    ticker: str
    base_currency: str = Field(min_length=3, max_length=3)
    money_weighted_return: Decimal | None = None
    money_weighted_return_status: HoldingReturnStatus
    valuation_date: date
    valuation_source: HoldingValuationSource = HoldingValuationSource.UNAVAILABLE
    valuation_provenance: MarketDataProvenance | None = None


class HoldingLedger(BaseModel):
    """Provider facts for a scoped return, separate from the public ledger API."""

    model_config = ConfigDict(frozen=True)
    transactions: tuple[Transaction, ...] = ()
    origins: tuple[LedgerOrigin, ...] = ()
    imports: tuple[HoldingImportHistory, ...] = ()
    has_unresolved_events: bool = False
    has_deleted_transactions: bool = False
    review_token: str | None = None
    saved_review_token: str | None = None
    confirmed_at: datetime | None = None


class AccountType(StrEnum):
    UNKNOWN = "UNKNOWN"
    TAXABLE = "TAXABLE"
    TRADITIONAL_401K = "TRADITIONAL_401K"
    ROTH_401K = "ROTH_401K"
    TRADITIONAL_IRA = "TRADITIONAL_IRA"
    ROTH_IRA = "ROTH_IRA"
    OTHER = "OTHER"


class PortfolioSummary(BaseModel):
    """Lightweight portfolio identity + reporting base currency (provider output)."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    base_currency: str = Field(min_length=3, max_length=3)
    account_type: AccountType = AccountType.UNKNOWN
    custodian: str | None = Field(default=None, max_length=120)
    external_account_id: str | None = Field(default=None, max_length=120)


class ClassificationSource(StrEnum):
    MANUAL = "MANUAL"
    PROVIDER = "PROVIDER"
    NONE = "NONE"


class DataGap(StrEnum):
    """Missing facts a user can supply; provider price availability is separate."""

    SECTOR = "SECTOR"
    INDUSTRY = "INDUSTRY"
    COST_BASIS = "COST_BASIS"
    CURRENCY = "CURRENCY"
    SPLIT_RATIO = "SPLIT_RATIO"
    TICKER = "TICKER"
    TRADE_DATE = "TRADE_DATE"
    QUANTITY = "QUANTITY"
    TRANSACTION = "TRANSACTION"


class HoldingInfo(BaseModel):
    """A tracked security's classification metadata (provider output).

    Grouping keys for allocation roll-ups; the market value is joined in later once
    the market-data layer (§1.3) can price the position.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1)
    sector: str | None = None
    industry: str | None = None
    classification_source: ClassificationSource = ClassificationSource.NONE
    data_gaps: tuple[DataGap, ...] = ()
    history_complete: bool = False
    history_gaps: tuple[HoldingHistoryGap, ...] = ()

    @model_validator(mode="after")
    def _classification_gaps(self) -> HoldingInfo:
        gaps = set(self.data_gaps) - {DataGap.SECTOR, DataGap.INDUSTRY}
        if not self.sector:
            gaps.add(DataGap.SECTOR)
        if not self.industry:
            gaps.add(DataGap.INDUSTRY)
        object.__setattr__(self, "data_gaps", tuple(sorted(gaps)))
        return self


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
    classification_source: ClassificationSource = ClassificationSource.NONE
    data_gaps: tuple[DataGap, ...] = ()
    history_complete: bool = False
    history_gaps: tuple[HoldingHistoryGap, ...] = ()


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


class MoneyWeightedReturnStatus(StrEnum):
    """Why the money-weighted return (XIRR) is, or is not, a number.

    A bare ``null`` cannot distinguish "this portfolio has too little history to
    have a return" from "we could not price your open positions today". Those
    call for completely different user action — enter more history versus
    configure market data — so the reason travels with the value.
    """

    OK = "OK"
    # Open positions exist but at least one could not be priced. The terminal
    # value would therefore be partial, and a partial terminal value silently
    # *understates* the return. We refuse to emit that number.
    UNPRICED_POSITIONS = "UNPRICED_POSITIONS"
    # Mathematically undefined: fewer than two distinct dated flows, or every
    # flow shares one sign so the net-present-value equation has no root.
    INSUFFICIENT_FLOWS = "INSUFFICIENT_FLOWS"


class PortfolioAnalytics(BaseModel):
    """Aggregated, base-currency portfolio analytics (the service layer's output).

    This is the single typed envelope the ``/analytics`` endpoint returns. It bundles
    the portfolio identity, per-position FIFO cost-basis results, whole-portfolio
    roll-up totals, and the money-weighted return (XIRR).

    ``money_weighted_return`` is ``None`` whenever XIRR is not trustworthy, and
    ``money_weighted_return_status`` says why — we surface "not computable"
    honestly rather than emitting a misleading ``0``. It is a *rate* (annualized
    fraction), not money, but is kept as ``Decimal`` so no ``float`` leaks into a
    financial payload.

    Note that XIRR on a portfolio holding open positions requires a **terminal
    value**: today's market value, treated as the inflow you would receive on
    liquidating. Without it a buy-only ledger has only negative flows and no root
    exists. That is why the return depends on market data being available, and why
    it is withheld (``UNPRICED_POSITIONS``) when any open position lacks a price.

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
    money_weighted_return_status: MoneyWeightedReturnStatus = (
        MoneyWeightedReturnStatus.INSUFFICIENT_FLOWS
    )

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
    account_type: AccountType = AccountType.UNKNOWN
    custodian: str | None = Field(default=None, max_length=120)
    external_account_id: str | None = Field(default=None, max_length=120)


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

        provided = (self.cost_basis_per_share is not None) + (self.total_cost_basis is not None)
        if provided != 1:
            raise ValueError("provide exactly one of 'cost_basis_per_share' or 'total_cost_basis'")
        return self


class HoldingClassificationUpdate(BaseModel):
    """Manual sector/industry override for one holding.

    Omitted fields are preserved; explicit null clears a field. Every edit marks
    the holding MANUAL, including clearing both fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sector: str | None = Field(default=None, min_length=1, max_length=80)
    industry: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> HoldingClassificationUpdate:
        if not self.model_fields_set:
            raise ValueError("provide at least one of 'sector' or 'industry'")
        if any(value is not None and not value.strip() for value in (self.sector, self.industry)):
            raise ValueError("use null to clear a field, not whitespace")
        return self


class ClassificationFailureReason(StrEnum):
    NO_PROFILE = "NO_PROFILE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


class ClassificationFailure(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    reason: ClassificationFailureReason


class HoldingClassificationResult(BaseModel):
    """Outcome of backfilling holdings' sector/industry from company profiles.

    Split three ways so the caller can tell progress from failure:

    * ``classified`` — holdings that now carry a sector and/or industry.
    * ``unresolved`` — the provider returned nothing usable (unknown symbol,
      quota exhausted, upstream down). Retrying later may succeed.
    * ``skipped`` — MANUAL or already carrying a classification; no lookup spent.

    ``remaining`` counts eligible tickers after this batch, not unresolved lookups.
    Continue with ``after_ticker=next_cursor`` using the same refresh policy until
    it reaches zero. For unchanged holdings it strictly decreases along that
    cursor chain, even on failure. Omitting the cursor starts a fresh sweep and
    retries unresolved tickers; that sequence has no decreasing-count guarantee.
    Repeats never create ledger events. Provider refreshes may change metadata as
    upstream profiles change, so they are safe but not an immutable snapshot.
    """

    model_config = ConfigDict(frozen=True)

    portfolio_id: int
    classified: tuple[HoldingInfo, ...] = ()
    unresolved: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    remaining: int = 0
    next_cursor: str | None = None
    failures: tuple[ClassificationFailure, ...] = ()


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
    unresolved_items: tuple[ImportIssue, ...] = ()


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

    PENDING = "PENDING"  # accepted + stored, not yet picked up
    RUNNING = "RUNNING"  # actively parsing/inserting
    SUCCEEDED = "SUCCEEDED"  # finished; transactions are in the ledger
    FAILED = "FAILED"  # aborted; see `error`


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
    history_complete: bool = False
    retry_safe: bool = True
    unresolved_items: tuple[UnresolvedItem, ...] = ()


class HoldingImportHistory(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: ImportStatus
    history_complete: bool


class UnresolvedKind(StrEnum):
    SPLIT_RATIO_UNKNOWN = "SPLIT_RATIO_UNKNOWN"
    TRANSFER_IN_NO_COST_BASIS = "TRANSFER_IN_NO_COST_BASIS"
    MISSING_DATA = "MISSING_DATA"
    UNSUPPORTED_ROW = "UNSUPPORTED_ROW"


class ImportIssue(BaseModel):
    """A source record requiring user review, independent of warning wording."""

    model_config = ConfigDict(frozen=True)
    kind: UnresolvedKind
    source_line: int
    ticker: str | None = None
    trade_date: date | None = None
    quantity: Decimal | None = None
    currency: str | None = None
    description: str = ""
    code: str = ""
    data_gaps: tuple[DataGap, ...] = ()


class UnresolvedItem(ImportIssue):
    id: int
    import_id: int
    portfolio_id: int
    resolved: bool = False


class UnresolvedResolution(BaseModel):
    """Supply a split, transfer opening lot, or corrected transaction explicitly."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    transaction: Transaction | None = None
    snapshot: PositionSnapshot | None = None

    @model_validator(mode="after")
    def _one_resolution(self) -> UnresolvedResolution:
        if (self.transaction is None) == (self.snapshot is None):
            raise ValueError("provide exactly one of transaction or snapshot")
        return self


ParsedStatement.model_rebuild()
StatementImportStatus.model_rebuild()
HoldingLedger.model_rebuild()
HistoryImportState.model_rebuild()
HoldingHistorySnapshot.model_rebuild()
