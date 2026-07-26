"""Schema shape, provenance, and immutability for market-data carriers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.marketdata.schemas import (
    CompanyProfile,
    FinancialLineItem,
    FinancialStatement,
    FinancialStatements,
    MarketDataProvenance,
    MarketDataType,
    Quote,
)

_PROV = MarketDataProvenance(
    provider_code="ALPHAVANTAGE",
    source_table="GLOBAL_QUOTE",
    as_of=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
)


def test_quote_requires_provenance() -> None:
    with pytest.raises(ValidationError):
        Quote(ticker="AAPL", price=Decimal("190.55"), currency="USD")  # type: ignore[call-arg]


def test_quote_is_frozen() -> None:
    quote = Quote(ticker="AAPL", price=Decimal("190.55"), currency="USD", provenance=_PROV)
    with pytest.raises(ValidationError):
        quote.price = Decimal("1")  # type: ignore[misc]


def test_missing_line_item_value_is_none_not_zero() -> None:
    item = FinancialLineItem(tag="grossProfit")
    assert item.value is None  # absent, explicitly — not a misleading 0


def test_financial_statements_container_groups_periods() -> None:
    stmt = FinancialStatement(
        ticker="AAPL",
        statement_type=MarketDataType.INCOME_STATEMENT,
        fiscal_date_ending=date(2025, 9, 30),
        currency="USD",
        line_items=(FinancialLineItem(tag="grossProfit", value=Decimal("100")),),
        provenance=_PROV,
    )
    statements = FinancialStatements(
        ticker="AAPL", statement_type=MarketDataType.INCOME_STATEMENT, statements=(stmt,)
    )
    assert len(statements.statements) == 1
    assert statements.statements[0].line_items[0].value == Decimal("100")


def test_profile_optional_fields_default_none() -> None:
    profile = CompanyProfile(ticker="AAPL", name="Apple Inc.", provenance=_PROV)
    assert profile.sector is None
    assert profile.industry is None

