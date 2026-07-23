"""Typed inputs/outputs for the portfolio calculators (AGENTS.md §8).

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

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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
