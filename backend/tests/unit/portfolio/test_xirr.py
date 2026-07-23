"""Money-weighted return (XIRR) tests with hand-/Excel-pinned expected values."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.currency import FxRateTable
from app.portfolio.calculators import XirrError, transactions_to_cash_flows, xirr
from app.portfolio.schemas import CashFlow, Transaction, TransactionType


def _cf(d: date, amount: str, currency: str = "USD") -> CashFlow:
    return CashFlow(date=d, amount=Decimal(amount), currency=currency)


def test_simple_ten_percent_annual(usd_only_fx: FxRateTable) -> None:
    # -1000 today, +1100 in exactly one year -> 10%.
    flows = [_cf(date(2026, 1, 1), "-1000"), _cf(date(2027, 1, 1), "1100")]
    assert xirr(flows, usd_only_fx) == pytest.approx(0.10, abs=1e-6)


def test_twenty_percent_annual(usd_only_fx: FxRateTable) -> None:
    flows = [_cf(date(2026, 1, 1), "-1000"), _cf(date(2027, 1, 1), "1200")]
    assert xirr(flows, usd_only_fx) == pytest.approx(0.20, abs=1e-6)


def test_negative_return(usd_only_fx: FxRateTable) -> None:
    flows = [_cf(date(2026, 1, 1), "-1000"), _cf(date(2027, 1, 1), "900")]
    assert xirr(flows, usd_only_fx) == pytest.approx(-0.10, abs=1e-6)


def test_excel_reference_example(usd_only_fx: FxRateTable) -> None:
    # Microsoft's documented XIRR example -> 0.373362535 (Actual/365).
    flows = [
        _cf(date(2008, 1, 1), "-10000"),
        _cf(date(2008, 3, 1), "2750"),
        _cf(date(2008, 10, 30), "4250"),
        _cf(date(2009, 2, 15), "3250"),
        _cf(date(2009, 4, 1), "2750"),
    ]
    assert xirr(flows, usd_only_fx) == pytest.approx(0.373362535, abs=1e-6)


def test_same_date_flows_are_aggregated(usd_only_fx: FxRateTable) -> None:
    # Two -500 outflows on the same day == one -1000 outflow.
    flows = [
        _cf(date(2026, 1, 1), "-500"),
        _cf(date(2026, 1, 1), "-500"),
        _cf(date(2027, 1, 1), "1100"),
    ]
    assert xirr(flows, usd_only_fx) == pytest.approx(0.10, abs=1e-6)


def test_mixed_currency_normalizes_to_base(usd_inr_fx: FxRateTable) -> None:
    # -1000 INR on 2026-01-10 (rate 0.012) = -12 USD; +13.2 USD one year later.
    # -12 + 13.2/(1.1) = 0 -> 10%.
    flows = [
        _cf(date(2026, 1, 10), "-1000", currency="INR"),
        _cf(date(2027, 1, 10), "13.2", currency="USD"),
    ]
    assert xirr(flows, usd_inr_fx) == pytest.approx(0.10, abs=1e-6)


def test_portfolio_level_merges_position_flows(usd_only_fx: FxRateTable) -> None:
    # Two positions' flows combined into a whole-portfolio XIRR.
    pos_a = [_cf(date(2026, 1, 1), "-1000"), _cf(date(2027, 1, 1), "1100")]
    pos_b = [_cf(date(2026, 1, 1), "-1000"), _cf(date(2027, 1, 1), "1100")]
    combined = pos_a + pos_b
    assert xirr(combined, usd_only_fx) == pytest.approx(0.10, abs=1e-6)


def test_too_few_flows_raises(usd_only_fx: FxRateTable) -> None:
    with pytest.raises(XirrError):
        xirr([_cf(date(2026, 1, 1), "-1000")], usd_only_fx)


def test_single_date_raises(usd_only_fx: FxRateTable) -> None:
    with pytest.raises(XirrError):
        xirr(
            [_cf(date(2026, 1, 1), "-1000"), _cf(date(2026, 1, 1), "1100")],
            usd_only_fx,
        )


def test_all_same_sign_raises(usd_only_fx: FxRateTable) -> None:
    with pytest.raises(XirrError):
        xirr(
            [_cf(date(2026, 1, 1), "-1000"), _cf(date(2027, 1, 1), "-500")],
            usd_only_fx,
        )


# --- transactions_to_cash_flows --------------------------------------------


def test_transactions_projected_with_correct_signs() -> None:
    txns = [
        Transaction(ticker="AAPL", currency="USD", type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100"), fees=Decimal("5")),
        Transaction(ticker="AAPL", currency="USD", type=TransactionType.DIVIDEND, trade_date=date(2026, 6, 1), amount=Decimal("30")),
        Transaction(ticker="AAPL", currency="USD", type=TransactionType.SELL, trade_date=date(2026, 9, 1), quantity=Decimal("10"), price=Decimal("120"), fees=Decimal("5")),
        Transaction(ticker="AAPL", currency="USD", type=TransactionType.FEE, trade_date=date(2026, 10, 1), amount=Decimal("15")),
        Transaction(ticker="AAPL", currency="USD", type=TransactionType.SPLIT, trade_date=date(2026, 11, 1), split_ratio=Decimal("2")),
    ]
    flows = transactions_to_cash_flows(txns)
    amounts = [f.amount for f in flows]
    # BUY: -(1000)-5 = -1005 ; DIV +30 ; SELL 1200-5 = +1195 ; FEE -15 ; SPLIT skipped
    assert amounts == [Decimal("-1005"), Decimal("30"), Decimal("1195"), Decimal("-15")]


def test_projected_flows_feed_xirr(usd_only_fx: FxRateTable) -> None:
    txns = [
        Transaction(ticker="AAPL", currency="USD", type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100")),
        Transaction(ticker="AAPL", currency="USD", type=TransactionType.SELL, trade_date=date(2027, 1, 1), quantity=Decimal("10"), price=Decimal("110")),
    ]
    flows = transactions_to_cash_flows(txns)
    assert xirr(flows, usd_only_fx) == pytest.approx(0.10, abs=1e-6)

