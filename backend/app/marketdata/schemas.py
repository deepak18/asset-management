"""Typed carriers for market data — the strongly-typed boundary (§8).

Every object here is a frozen Pydantic model (immutable recorded fact) and every
externally-sourced datum carries a :class:`MarketDataProvenance`. That provenance
is the *structured-data citation* unit from PLAN.md §7 (``Provider_Code`` +
``Data_Source_Table`` + ``As_Of_Timestamp``): the AI layer may never surface a
market figure without being able to point back to where it came from and when.

``Decimal`` (never ``float``) for all money, matching the ledger's exactness rule.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MarketDataType(StrEnum):
    """The kinds of market data we fetch + cache (also the cache ``data_type`` key)."""

    QUOTE = "QUOTE"
    PROFILE = "PROFILE"
    INCOME_STATEMENT = "INCOME_STATEMENT"
    BALANCE_SHEET = "BALANCE_SHEET"
    CASH_FLOW = "CASH_FLOW"


class MarketDataProvenance(BaseModel):
    """Where a datum came from + as-of when (PLAN.md §7 structured citation unit).

    * ``provider_code`` — the source system, e.g. ``"ALPHAVANTAGE"``.
    * ``source_table``  — the logical source within it (e.g. the AlphaVantage
      function ``"GLOBAL_QUOTE"``), decoupled from any table formatting.
    * ``as_of``         — the timestamp the source attributes to the datum
      (tz-aware), enabling restatement auditing.
    """

    model_config = ConfigDict(frozen=True)

    provider_code: str = Field(min_length=1)
    source_table: str = Field(min_length=1)
    as_of: datetime


class Quote(BaseModel):
    """A last-known price for one ticker, in its native currency."""

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1)
    price: Decimal
    currency: str = Field(min_length=3, max_length=3)
    provenance: MarketDataProvenance


class CompanyProfile(BaseModel):
    """Descriptive company metadata (name, sector/industry, description)."""

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None
    provenance: MarketDataProvenance


class FinancialLineItem(BaseModel):
    """One normalized line of a financial statement.

    ``value`` is optional because sources routinely omit individual lines; a
    missing line is represented explicitly as ``None`` rather than ``0`` (which
    would be a wrong number, not an absent one).
    """

    model_config = ConfigDict(frozen=True)

    tag: str = Field(min_length=1)
    value: Decimal | None = None


class FinancialStatement(BaseModel):
    """A single fiscal period of one statement (income / balance / cash-flow)."""

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1)
    statement_type: MarketDataType
    fiscal_date_ending: date
    currency: str = Field(min_length=3, max_length=3)
    line_items: tuple[FinancialLineItem, ...]
    provenance: MarketDataProvenance


class FinancialStatements(BaseModel):
    """A multi-period set of one statement type — a single cacheable object.

    Wrapping the periods in one model keeps the cache uniform: every cache key
    maps to exactly one Pydantic object, whether that's a ``Quote`` or a whole
    history of income statements.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1)
    statement_type: MarketDataType
    statements: tuple[FinancialStatement, ...]

