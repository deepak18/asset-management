"""Pure source reconciliation; never guess missing history or transfer basis."""

from decimal import Decimal

from app.portfolio.ingest import snapshot_to_opening_buy
from app.portfolio.schemas import (
    ImportIssue,
    ParsedStatement,
    Transaction,
    TransactionType,
    UnresolvedKind,
    UnresolvedResolution,
)


def infer_splits(parsed: ParsedStatement, history_complete: bool) -> ParsedStatement:
    """Infer only corroborated, unambiguous share deltas in confirmed full history.

    Share quantities in exports are rounded. A near-integral forward ratio (or
    reciprocal reverse ratio) is accepted only if its resulting share delta agrees
    within one millionth of a share. Same-day trades have no reliable time order.
    """

    if not history_complete:
        return parsed
    transactions = list(parsed.transactions)
    remaining: list[ImportIssue] = []
    inferred_lines: set[int] = set()
    warnings = list(parsed.warnings)
    issues = sorted(
        parsed.unresolved_items, key=lambda item: (str(item.trade_date or ""), item.source_line)
    )
    for item in issues:
        if (
            item.kind != UnresolvedKind.SPLIT_RATIO_UNKNOWN
            or not item.ticker
            or not item.trade_date
            or item.quantity is None
        ):
            remaining.append(item)
            continue
        blocked = any(
            (other.ticker is None or other.ticker == item.ticker)
            and other is not item
            and (other.trade_date is None or other.trade_date <= item.trade_date)
            for other in remaining
        )
        same_day = any(
            t.ticker == item.ticker and t.trade_date == item.trade_date for t in transactions
        )
        same_day_issue = any(
            other is not item
            and other.ticker == item.ticker
            and other.trade_date == item.trade_date
            for other in issues
        )
        quantity = Decimal(0)
        valid = not blocked and not same_day and not same_day_issue
        for txn in sorted(transactions, key=lambda t: t.trade_date):
            if txn.ticker != item.ticker or txn.trade_date >= item.trade_date:
                continue
            if txn.currency != item.currency:
                valid = False
            if txn.type == TransactionType.BUY:
                quantity += txn.quantity
            elif txn.type == TransactionType.SELL:
                quantity -= txn.quantity
            elif txn.type == TransactionType.SPLIT:
                quantity *= txn.split_ratio
            if quantity < 0:
                valid = False
        delta = -abs(item.quantity) if item.code == "SPR" else item.quantity
        if not valid or quantity <= 0 or quantity + delta <= 0:
            remaining.append(item)
            continue
        raw_ratio = (quantity + delta) / quantity
        if raw_ratio > 1:
            ratio = raw_ratio.to_integral_value()
        else:
            denominator = (1 / raw_ratio).to_integral_value()
            ratio = 1 / denominator if denominator else Decimal(0)
        if ratio <= 0 or ratio == 1 or abs(quantity * (ratio - 1) - delta) > Decimal("0.000001"):
            remaining.append(item)
            continue
        transactions.append(
            Transaction(
                ticker=item.ticker,
                type=TransactionType.SPLIT,
                trade_date=item.trade_date,
                currency=item.currency or "USD",
                split_ratio=ratio,
            )
        )
        inferred_lines.add(item.source_line)
        warnings.append(
            f"row {item.source_line}: inferred {item.ticker} split ratio {ratio} "
            "from confirmed complete history"
        )
    warnings = [
        w
        for w in warnings
        if not any(w.startswith(f"row {line}: skipped ") for line in inferred_lines)
    ]
    return ParsedStatement(
        source_format=parsed.source_format,
        transactions=tuple(sorted(transactions, key=lambda t: t.trade_date)),
        warnings=tuple(warnings),
        unresolved_items=tuple(remaining),
    )


def correction_transaction(item: ImportIssue, resolution: UnresolvedResolution) -> Transaction:
    """Validate a correction against known source facts before any write occurs."""

    if item.kind == UnresolvedKind.TRANSFER_IN_NO_COST_BASIS:
        if resolution.snapshot is None:
            raise ValueError("a transferred-in position requires a snapshot with real cost basis")
        snapshot = resolution.snapshot
        # Use the transfer date for the opening lot, not a pre-transfer split date.
        if snapshot.as_of is None and item.trade_date is not None:
            snapshot = snapshot.model_copy(update={"as_of": item.trade_date})
        txn = snapshot_to_opening_buy(snapshot)
    else:
        if resolution.transaction is None:
            raise ValueError("this item requires a corrected transaction")
        txn = resolution.transaction
    if item.ticker and txn.ticker.upper() != item.ticker:
        raise ValueError("ticker must match the source item")
    if item.trade_date and txn.trade_date != item.trade_date:
        raise ValueError("trade_date must match the source item")
    if item.currency and txn.currency.upper() != item.currency:
        raise ValueError("currency must match the source item")
    if item.kind == UnresolvedKind.TRANSFER_IN_NO_COST_BASIS and txn.quantity != item.quantity:
        raise ValueError("quantity must match the transferred shares")
    if item.kind == UnresolvedKind.SPLIT_RATIO_UNKNOWN and txn.type != TransactionType.SPLIT:
        raise ValueError("a split item requires a SPLIT transaction")
    if txn.type == TransactionType.SPLIT and (txn.split_ratio <= 0 or txn.split_ratio == 1):
        raise ValueError("split_ratio must be positive and different from one")
    if txn.type in (TransactionType.BUY, TransactionType.SELL) and (
        txn.quantity <= 0 or txn.price < 0
    ):
        raise ValueError("trades require positive quantity and nonnegative price")
    if txn.type in (TransactionType.FEE, TransactionType.DIVIDEND) and txn.amount <= 0:
        raise ValueError("cash events require positive amount")
    return txn.model_copy(update={"ticker": txn.ticker.upper(), "currency": txn.currency.upper()})
