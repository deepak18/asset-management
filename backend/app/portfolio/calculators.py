"""Deterministic, side-effect-free portfolio calculators (PLAN.md §1.2, AGENTS.md §1).

Everything here is **pure Python**: no DB, no network, no MCP, no AI. Given the
same inputs (a ledger of :class:`~app.portfolio.schemas.Transaction` and an injected
:class:`~app.core.currency.FxRateTable`) these functions always return the same
result. That determinism is exactly why the financial math must live in code and
never in an LLM (AGENTS.md §1).

Lot method
----------
Realized P&L uses **FIFO** (first-in, first-out): sells consume the oldest open
lots first. This is a deliberate, documented choice — it is the most common default
for retail brokerage cost-basis reporting and keeps the algorithm order-stable.

Currency
--------
Every native-currency figure is normalized to the portfolio base currency using the
**transaction-date** FX rate, via the injected :class:`FxRateTable`. USD is enabled
now; INR (or anything else) becomes available purely by injecting more rates.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.currency import FxRateTable, Money
from app.portfolio.schemas import (
    AllocationWeight,
    CashFlow,
    CostBasisResult,
    OpenLot,
    PositionValue,
    Transaction,
    TransactionType,
    UnrealizedResult,
)

__all__ = [
    "allocation_weights",
    "cost_basis_fifo",
    "unrealized_pnl",
    "transactions_to_cash_flows",
    "xirr",
    "XirrError",
]


# ---------------------------------------------------------------------------
# 1) Asset allocation weights
# ---------------------------------------------------------------------------


def allocation_weights(
    positions: list[PositionValue],
    group_by: str = "ticker",
) -> list[AllocationWeight]:
    """Compute allocation weights from base-currency position values.

    ``group_by`` is one of ``"ticker"`` (default), ``"sector"`` or ``"industry"``;
    the grouping seam makes sector/industry roll-ups a one-line call. Positions
    missing a grouping attribute are bucketed under ``"UNCLASSIFIED"``.

    Weights are fractions in ``[0, 1]`` that sum to ``1`` across a non-empty,
    positive-value breakdown. An empty ledger returns ``[]``. Rows are sorted by
    descending market value then key for stable output.
    """

    if group_by not in {"ticker", "sector", "industry"}:
        raise ValueError(f"Unsupported group_by: {group_by!r}")
    if not positions:
        return []

    grouped: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for pos in positions:
        if group_by == "ticker":
            key = pos.ticker
        else:
            key = getattr(pos, group_by) or "UNCLASSIFIED"
        grouped[key] += pos.market_value

    total = sum(grouped.values(), Decimal(0))
    rows: list[AllocationWeight] = []
    for key, value in grouped.items():
        weight = (value / total) if total != 0 else Decimal(0)
        rows.append(AllocationWeight(key=key, market_value=value, weight=weight))

    rows.sort(key=lambda r: (-r.market_value, r.key))
    return rows


# ---------------------------------------------------------------------------
# 2) Cost-basis tracking + realized P&L (FIFO)
# ---------------------------------------------------------------------------


def _to_base(fx: FxRateTable, amount: Decimal, currency: str, on_date: date) -> Decimal:
    return fx.to_base(Money(amount=amount, currency=currency), on_date).amount


@dataclass
class _MutableLot:
    """Internal, mutable FIFO lot used only while replaying the ledger."""

    quantity: Decimal
    cost_per_share_base: Decimal
    trade_date: date


def cost_basis_fifo(
    transactions: list[Transaction],
    fx: FxRateTable,
) -> CostBasisResult:
    """Replay one ticker's ledger under FIFO and return open lots + realized P&L.

    Supported events: ``BUY`` (opens a lot), ``SELL`` (closes oldest lots first,
    realizing P&L), ``SPLIT`` (adjusts open-lot share counts and per-share cost so
    total basis is preserved), ``DIVIDEND`` and ``FEE`` (tracked separately; fees on
    buys/sells are folded into cost basis / proceeds).

    All figures are normalized to ``fx.base_currency`` at each event's trade date.
    Realized P&L for a sell = base proceeds (net of sell fees) − base cost basis of
    the consumed lots. An empty ledger yields zeroed totals.
    """

    if not transactions:
        return CostBasisResult(
            ticker="",
            open_quantity=Decimal(0),
            open_cost_basis_base=Decimal(0),
            realized_pnl_base=Decimal(0),
            dividends_base=Decimal(0),
            fees_base=Decimal(0),
            open_lots=(),
        )

    tickers = {t.ticker for t in transactions}
    if len(tickers) != 1:
        raise ValueError(f"cost_basis_fifo expects a single ticker, got {sorted(tickers)}")
    ticker = next(iter(tickers))

    ordered = sorted(transactions, key=lambda t: t.trade_date)

    # Each open lot: mutable [quantity, cost_per_share_base, trade_date]
    lots: list[_MutableLot] = []
    realized = Decimal(0)
    dividends = Decimal(0)
    fees_total = Decimal(0)

    for txn in ordered:
        if txn.type is TransactionType.BUY:
            if txn.quantity <= 0:
                raise ValueError("BUY quantity must be positive")
            gross = txn.quantity * txn.price
            fee_base = _to_base(fx, txn.fees, txn.currency, txn.trade_date)
            gross_base = _to_base(fx, gross, txn.currency, txn.trade_date)
            fees_total += fee_base
            cost_base = gross_base + fee_base  # buy fees increase cost basis
            cost_per_share = cost_base / txn.quantity
            lots.append(
                _MutableLot(
                    quantity=txn.quantity,
                    cost_per_share_base=cost_per_share,
                    trade_date=txn.trade_date,
                )
            )

        elif txn.type is TransactionType.SELL:
            if txn.quantity <= 0:
                raise ValueError("SELL quantity must be positive")
            open_qty = sum((lot.quantity for lot in lots), Decimal(0))
            if txn.quantity > open_qty:
                raise ValueError(
                    f"Cannot SELL {txn.quantity} of {ticker}; only {open_qty} open"
                )
            fee_base = _to_base(fx, txn.fees, txn.currency, txn.trade_date)
            fees_total += fee_base
            proceeds_base = _to_base(
                fx, txn.quantity * txn.price, txn.currency, txn.trade_date
            )
            proceeds_base -= fee_base  # sell fees reduce proceeds

            remaining = txn.quantity
            consumed_cost = Decimal(0)
            while remaining > 0:
                lot = lots[0]
                take = min(lot.quantity, remaining)
                consumed_cost += take * lot.cost_per_share_base
                lot.quantity -= take
                remaining -= take
                if lot.quantity == 0:
                    lots.pop(0)
            realized += proceeds_base - consumed_cost

        elif txn.type is TransactionType.SPLIT:
            ratio = txn.split_ratio
            if ratio <= 0:
                raise ValueError("SPLIT ratio must be positive")
            for lot in lots:
                lot.quantity = lot.quantity * ratio
                lot.cost_per_share_base = lot.cost_per_share_base / ratio

        elif txn.type is TransactionType.DIVIDEND:
            dividends += _to_base(fx, txn.amount, txn.currency, txn.trade_date)

        elif txn.type is TransactionType.FEE:
            fee_base = _to_base(fx, txn.amount, txn.currency, txn.trade_date)
            fees_total += fee_base
            realized -= fee_base  # standalone fees reduce realized P&L

    open_quantity = sum((lot.quantity for lot in lots), Decimal(0))
    open_cost_basis = sum(
        (lot.quantity * lot.cost_per_share_base for lot in lots), Decimal(0)
    )
    open_lots = tuple(
        OpenLot(
            trade_date=lot.trade_date,
            quantity=lot.quantity,
            cost_per_share_base=lot.cost_per_share_base,
        )
        for lot in lots
    )

    return CostBasisResult(
        ticker=ticker,
        open_quantity=open_quantity,
        open_cost_basis_base=open_cost_basis,
        realized_pnl_base=realized,
        dividends_base=dividends,
        fees_base=fees_total,
        open_lots=open_lots,
    )


# ---------------------------------------------------------------------------
# 3) Unrealized P&L (cost basis vs. current price)
# ---------------------------------------------------------------------------


def unrealized_pnl(
    cost_basis: CostBasisResult,
    current_price: Decimal,
    price_currency: str,
    as_of: date,
    fx: FxRateTable,
) -> UnrealizedResult:
    """Mark open lots to market against ``current_price`` (native currency).

    Market value and unrealized P&L are expressed in ``fx.base_currency`` using the
    ``as_of`` FX rate. A flat/empty position yields zeroed market value and P&L.
    """

    market_value_base = _to_base(
        fx, cost_basis.open_quantity * current_price, price_currency, as_of
    )
    return UnrealizedResult(
        ticker=cost_basis.ticker,
        open_quantity=cost_basis.open_quantity,
        open_cost_basis_base=cost_basis.open_cost_basis_base,
        market_value_base=market_value_base,
        unrealized_pnl_base=market_value_base - cost_basis.open_cost_basis_base,
    )


# ---------------------------------------------------------------------------
# 4) Money-weighted return (XIRR)
# ---------------------------------------------------------------------------


class XirrError(ValueError):
    """Raised when XIRR is undefined (too few flows, single sign, no convergence)."""


def transactions_to_cash_flows(transactions: list[Transaction]) -> list[CashFlow]:
    """Project ledger events into signed investor cash flows for XIRR.

    Sign convention (investor perspective): BUY and FEE are outflows (negative);
    SELL and DIVIDEND are inflows (positive). Per-transaction ``fees`` on buys/sells
    are folded into the same-dated flow. ``SPLIT`` events carry no cash and are
    skipped. Native currencies are preserved; :func:`xirr` normalizes them.
    """

    flows: list[CashFlow] = []
    for txn in transactions:
        if txn.type is TransactionType.BUY:
            amount = -(txn.quantity * txn.price) - txn.fees
        elif txn.type is TransactionType.SELL:
            amount = (txn.quantity * txn.price) - txn.fees
        elif txn.type is TransactionType.DIVIDEND:
            amount = txn.amount
        elif txn.type is TransactionType.FEE:
            amount = -txn.amount
        else:  # SPLIT — no cash flow
            continue
        flows.append(CashFlow(date=txn.trade_date, amount=amount, currency=txn.currency))
    return flows


def _xnpv(rate: float, amounts: list[float], years: list[float]) -> float:
    return float(sum(a / (1.0 + rate) ** y for a, y in zip(amounts, years, strict=True)))


def _xnpv_derivative(rate: float, amounts: list[float], years: list[float]) -> float:
    return float(
        sum(-y * a / (1.0 + rate) ** (y + 1.0) for a, y in zip(amounts, years, strict=True))
    )


def xirr(
    cash_flows: list[CashFlow],
    fx: FxRateTable,
    guess: float = 0.1,
    day_count: float = 365.0,
    max_iterations: int = 100,
    tolerance: float = 1e-9,
) -> float:
    """Money-weighted return (XIRR) of dated cash flows, base-currency normalized.

    Solves for the annualized rate ``r`` where the base-currency net present value is
    zero, using an Actual/``day_count`` (default 365) day-count convention:

        ``sum( cf_i / (1 + r) ** (days_i / day_count) ) == 0``

    Cash flows are converted to ``fx.base_currency`` at each flow's own date, so a
    mixed-currency ledger produces a single, coherent investor return. Flows on the
    same date are aggregated.

    Raises :class:`XirrError` when the return is undefined: fewer than two net-dated
    flows, all flows share one sign (no root), or the solver fails to converge.
    Newton–Raphson is attempted first, then a robust bisection fallback.
    """

    if len(cash_flows) < 2:
        raise XirrError("XIRR needs at least two cash flows")

    # Normalize to base currency at each flow's own date, then aggregate per date.
    # NOTE: we intentionally drop from Decimal to float here. Root-finding needs
    # fractional exponentiation ((1 + r) ** (days / 365)), which Decimal does not
    # support. float precision is fine because the result is a *rate* asserted
    # against hand-computed fixtures with tolerances — not a stored ledger amount.
    by_date: dict[date, float] = defaultdict(float)
    for cf in cash_flows:
        base_amt = fx.to_base(Money(amount=cf.amount, currency=cf.currency), cf.date).amount
        by_date[cf.date] += float(base_amt)

    if len(by_date) < 2:
        raise XirrError("XIRR needs cash flows on at least two distinct dates")

    dates = sorted(by_date)
    t0 = dates[0]
    amounts = [by_date[d] for d in dates]
    years = [(d - t0).days / day_count for d in dates]

    has_positive = any(a > 0 for a in amounts)
    has_negative = any(a < 0 for a in amounts)
    if not (has_positive and has_negative):
        raise XirrError("XIRR requires at least one inflow and one outflow")

    # --- Newton–Raphson ---
    rate = guess
    for _ in range(max_iterations):
        try:
            value = _xnpv(rate, amounts, years)
            derivative = _xnpv_derivative(rate, amounts, years)
        except (OverflowError, ZeroDivisionError):
            break
        if derivative == 0:
            break
        new_rate = rate - value / derivative
        if new_rate <= -1.0:  # keep (1 + r) positive so powers stay real
            new_rate = (rate - 1.0) / 2.0
        if abs(new_rate - rate) < tolerance:
            return new_rate
        rate = new_rate

    # --- Bisection fallback over a wide bracket ---
    low, high = -0.9999999, 100.0
    f_low = _xnpv(low, amounts, years)
    f_high = _xnpv(high, amounts, years)
    if f_low * f_high > 0:
        raise XirrError("XIRR did not converge (no sign change in bracket)")
    for _ in range(1000):
        mid = (low + high) / 2.0
        f_mid = _xnpv(mid, amounts, years)
        if abs(f_mid) < tolerance:
            return mid
        if f_low * f_mid < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid
    raise XirrError("XIRR did not converge")
