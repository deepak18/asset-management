"""Edge-case tests for the FX normalization seam (app.core.currency)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.currency import FxRate, FxRateTable, MissingFxRateError, Money


def test_base_currency_is_identity(usd_only_fx: FxRateTable) -> None:
    money = Money(amount=Decimal("100"), currency="USD")
    out = usd_only_fx.to_base(money, date(2026, 1, 10))
    assert out == Money(amount=Decimal("100"), currency="USD")


def test_to_base_uses_transaction_date_rate(usd_inr_fx: FxRateTable) -> None:
    jan = usd_inr_fx.to_base(Money(amount=Decimal("1000"), currency="INR"), date(2026, 1, 10))
    jun = usd_inr_fx.to_base(Money(amount=Decimal("1000"), currency="INR"), date(2026, 6, 10))
    assert jan.amount == Decimal("12.000")
    assert jun.amount == Decimal("11.000")
    assert jan.currency == "USD"


def test_missing_rate_raises(usd_inr_fx: FxRateTable) -> None:
    with pytest.raises(MissingFxRateError):
        usd_inr_fx.to_base(Money(amount=Decimal("1"), currency="INR"), date(2026, 3, 1))


def test_missing_currency_raises(usd_only_fx: FxRateTable) -> None:
    with pytest.raises(MissingFxRateError):
        usd_only_fx.to_base(Money(amount=Decimal("1"), currency="EUR"), date(2026, 1, 10))


def test_convert_same_currency_is_noop(usd_inr_fx: FxRateTable) -> None:
    money = Money(amount=Decimal("50"), currency="INR")
    assert usd_inr_fx.convert(money, "INR", date(2026, 1, 10)) == money


def test_convert_base_to_foreign(usd_inr_fx: FxRateTable) -> None:
    # 12 USD -> INR at 0.012 USD/INR == 1000 INR
    out = usd_inr_fx.convert(Money(amount=Decimal("12"), currency="USD"), "INR", date(2026, 1, 10))
    assert out.currency == "INR"
    assert out.amount == Decimal("1000")


def test_convert_foreign_to_foreign_via_base() -> None:
    fx = FxRateTable(
        base_currency="USD",
        rates=(
            FxRate(currency="INR", as_of=date(2026, 1, 10), rate_to_base=Decimal("0.012")),
            FxRate(currency="EUR", as_of=date(2026, 1, 10), rate_to_base=Decimal("1.10")),
        ),
    )
    # 1100 INR -> USD 13.2 -> EUR 12
    out = fx.convert(Money(amount=Decimal("1100"), currency="INR"), "EUR", date(2026, 1, 10))
    assert out.currency == "EUR"
    assert out.amount == Decimal("12")


def test_money_is_frozen() -> None:
    money = Money(amount=Decimal("1"), currency="USD")
    with pytest.raises(ValidationError):
        money.amount = Decimal("2")  # type: ignore[misc]


def test_rate_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        FxRate(currency="INR", as_of=date(2026, 1, 10), rate_to_base=Decimal("0"))
