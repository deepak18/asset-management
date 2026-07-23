"""FIFO cost-basis, realized & unrealized P&L tests.

All expected values are hand-computed in the docstrings/comments so the fixtures
double as the specification.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.currency import FxRateTable
from app.portfolio.calculators import cost_basis_fifo, unrealized_pnl
from app.portfolio.schemas import Transaction, TransactionType


def _txn(**kw: object) -> Transaction:
    base = dict(ticker="AAPL", currency="USD")
    base.update(kw)
    return Transaction(**base)  # type: ignore[arg-type]


def test_empty_ledger_zeroed(usd_only_fx: FxRateTable) -> None:
    res = cost_basis_fifo([], usd_only_fx)
    assert res.open_quantity == Decimal("0")
    assert res.open_cost_basis_base == Decimal("0")
    assert res.realized_pnl_base == Decimal("0")
    assert res.open_lots == ()


def test_single_buy(usd_only_fx: FxRateTable) -> None:
    res = cost_basis_fifo(
        [_txn(type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100"))],
        usd_only_fx,
    )
    assert res.open_quantity == Decimal("10")
    assert res.open_cost_basis_base == Decimal("1000")
    assert res.realized_pnl_base == Decimal("0")


def test_buy_fees_increase_cost_basis(usd_only_fx: FxRateTable) -> None:
    res = cost_basis_fifo(
        [_txn(type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100"), fees=Decimal("10"))],
        usd_only_fx,
    )
    assert res.open_cost_basis_base == Decimal("1010")
    assert res.fees_base == Decimal("10")


def test_partial_sell_fifo_across_two_lots(usd_only_fx: FxRateTable) -> None:
    # Lot1: 10@100 (Jan), Lot2: 10@120 (Feb). Sell 15@150 (Mar).
    # Consumed cost = 10*100 + 5*120 = 1600; proceeds = 2250; realized = 650.
    # Remaining: 5@120 = 600 basis.
    txns = [
        _txn(type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100")),
        _txn(type=TransactionType.BUY, trade_date=date(2026, 2, 1), quantity=Decimal("10"), price=Decimal("120")),
        _txn(type=TransactionType.SELL, trade_date=date(2026, 3, 1), quantity=Decimal("15"), price=Decimal("150")),
    ]
    res = cost_basis_fifo(txns, usd_only_fx)
    assert res.realized_pnl_base == Decimal("650")
    assert res.open_quantity == Decimal("5")
    assert res.open_cost_basis_base == Decimal("600")
    assert len(res.open_lots) == 1
    assert res.open_lots[0].cost_per_share_base == Decimal("120")


def test_sell_fees_reduce_proceeds(usd_only_fx: FxRateTable) -> None:
    # Buy 10@100; sell 10@150 fee 20 -> proceeds 1480; realized 480.
    txns = [
        _txn(type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100")),
        _txn(type=TransactionType.SELL, trade_date=date(2026, 2, 1), quantity=Decimal("10"), price=Decimal("150"), fees=Decimal("20")),
    ]
    res = cost_basis_fifo(txns, usd_only_fx)
    assert res.realized_pnl_base == Decimal("480")
    assert res.open_quantity == Decimal("0")


def test_split_preserves_basis_then_sell(usd_only_fx: FxRateTable) -> None:
    # Buy 10@100 -> 2:1 split -> 20@50. Sell 5@60 -> proceeds 300, cost 250, realized 50.
    txns = [
        _txn(type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100")),
        _txn(type=TransactionType.SPLIT, trade_date=date(2026, 2, 1), split_ratio=Decimal("2")),
        _txn(type=TransactionType.SELL, trade_date=date(2026, 3, 1), quantity=Decimal("5"), price=Decimal("60")),
    ]
    res = cost_basis_fifo(txns, usd_only_fx)
    assert res.realized_pnl_base == Decimal("50")
    assert res.open_quantity == Decimal("15")
    assert res.open_cost_basis_base == Decimal("750")


def test_dividend_tracked_separately(usd_only_fx: FxRateTable) -> None:
    txns = [
        _txn(type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100")),
        _txn(type=TransactionType.DIVIDEND, trade_date=date(2026, 2, 1), amount=Decimal("50")),
    ]
    res = cost_basis_fifo(txns, usd_only_fx)
    assert res.dividends_base == Decimal("50")
    assert res.realized_pnl_base == Decimal("0")


def test_standalone_fee_reduces_realized(usd_only_fx: FxRateTable) -> None:
    txns = [
        _txn(type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100")),
        _txn(type=TransactionType.FEE, trade_date=date(2026, 2, 1), amount=Decimal("25")),
    ]
    res = cost_basis_fifo(txns, usd_only_fx)
    assert res.realized_pnl_base == Decimal("-25")
    assert res.fees_base == Decimal("25")


def test_oversell_raises(usd_only_fx: FxRateTable) -> None:
    txns = [
        _txn(type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("5"), price=Decimal("100")),
        _txn(type=TransactionType.SELL, trade_date=date(2026, 2, 1), quantity=Decimal("10"), price=Decimal("150")),
    ]
    with pytest.raises(ValueError):
        cost_basis_fifo(txns, usd_only_fx)


def test_multiple_tickers_raises(usd_only_fx: FxRateTable) -> None:
    txns = [
        _txn(ticker="AAPL", type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("1"), price=Decimal("1")),
        _txn(ticker="MSFT", type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("1"), price=Decimal("1")),
    ]
    with pytest.raises(ValueError):
        cost_basis_fifo(txns, usd_only_fx)


def test_mixed_currency_buy_then_sell(usd_inr_fx: FxRateTable) -> None:
    # Buy 100@10 INR on Jan-10 (rate 0.012) -> base cost 12 USD (0.12/share).
    # Sell 100@12 INR on Jun-10 (rate 0.011) -> proceeds 1200 INR = 13.2 USD.
    # Realized = 13.2 - 12 = 1.2 USD.
    txns = [
        Transaction(ticker="INFY", currency="INR", type=TransactionType.BUY, trade_date=date(2026, 1, 10), quantity=Decimal("100"), price=Decimal("10")),
        Transaction(ticker="INFY", currency="INR", type=TransactionType.SELL, trade_date=date(2026, 6, 10), quantity=Decimal("100"), price=Decimal("12")),
    ]
    res = cost_basis_fifo(txns, usd_inr_fx)
    assert res.open_quantity == Decimal("0")
    assert res.realized_pnl_base == Decimal("1.2")


# --- Unrealized P&L ---------------------------------------------------------


def test_unrealized_gain(usd_only_fx: FxRateTable) -> None:
    res = cost_basis_fifo(
        [_txn(type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100"))],
        usd_only_fx,
    )
    unreal = unrealized_pnl(res, Decimal("150"), "USD", date(2026, 6, 1), usd_only_fx)
    assert unreal.market_value_base == Decimal("1500")
    assert unreal.unrealized_pnl_base == Decimal("500")


def test_unrealized_loss(usd_only_fx: FxRateTable) -> None:
    res = cost_basis_fifo(
        [_txn(type=TransactionType.BUY, trade_date=date(2026, 1, 1), quantity=Decimal("10"), price=Decimal("100"))],
        usd_only_fx,
    )
    unreal = unrealized_pnl(res, Decimal("80"), "USD", date(2026, 6, 1), usd_only_fx)
    assert unreal.unrealized_pnl_base == Decimal("-200")


def test_unrealized_flat_position_is_zero(usd_only_fx: FxRateTable) -> None:
    res = cost_basis_fifo([], usd_only_fx)
    unreal = unrealized_pnl(res, Decimal("100"), "USD", date(2026, 6, 1), usd_only_fx)
    assert unreal.market_value_base == Decimal("0")
    assert unreal.unrealized_pnl_base == Decimal("0")


def test_unrealized_mixed_currency(usd_inr_fx: FxRateTable) -> None:
    # Hold 100 shares cost basis 12 USD; mark at 15 INR on Jun-10 (rate 0.011).
    # Market value = 100*15*0.011 = 16.5 USD; unrealized = 4.5 USD.
    res = cost_basis_fifo(
        [Transaction(ticker="INFY", currency="INR", type=TransactionType.BUY, trade_date=date(2026, 1, 10), quantity=Decimal("100"), price=Decimal("10"))],
        usd_inr_fx,
    )
    unreal = unrealized_pnl(res, Decimal("15"), "INR", date(2026, 6, 10), usd_inr_fx)
    assert unreal.market_value_base == Decimal("16.500")
    assert unreal.unrealized_pnl_base == Decimal("4.500")
