"""Pure history diagnostics shared by holding reads and return orchestration."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, DecimalException
from hashlib import sha256

from app.portfolio.schemas import (
    HoldingHistoryGap,
    HoldingHistorySnapshot,
    HoldingLedger,
    ImportStatus,
    LedgerOrigin,
    Transaction,
    TransactionType,
)

ACKNOWLEDGEABLE_GAPS = frozenset({
    HoldingHistoryGap.UNKNOWN_ORIGIN, HoldingHistoryGap.IMPORT_NOT_COMPLETE,
    HoldingHistoryGap.DELETED_TRANSACTION, HoldingHistoryGap.HISTORY_CHANGED,
})


class HistoryConfirmationConflict(ValueError):
    """The reviewed snapshot changed or contains non-acknowledgeable gaps."""


def history_review_token(snapshot: HoldingHistorySnapshot) -> str:
    """Hash typed facts only; confirmation and volatile progress are not inputs.

    Canonical ordering is explicit so row enumeration never changes a token.
    Decimal representations remain lossless; no float conversion is involved.
    """
    canonical = snapshot.model_copy(update={
        "ticker": snapshot.ticker.upper(),
        "transactions": tuple(sorted(snapshot.transactions, key=lambda event: event.id)),
        "imports": tuple(job.model_copy(update={
            "tickers": tuple(sorted(ticker.upper() for ticker in job.tickers)),
            "unresolved_items": tuple(sorted(job.unresolved_items, key=lambda item: item.id)),
        }) for job in sorted(snapshot.imports, key=lambda job: job.id)),
    })
    return sha256(canonical.model_dump_json().encode("utf-8")).hexdigest()


def blocking_history_gaps(
    gaps: Sequence[HoldingHistoryGap],
) -> tuple[HoldingHistoryGap, ...]:
    return tuple(sorted(set(gaps) - ACKNOWLEDGEABLE_GAPS))


def confirmation_is_effective(ledger: HoldingLedger, *, as_of: date | None = None) -> bool:
    return bool(
        ledger.confirmed_at is not None and ledger.review_token is not None
        and ledger.saved_review_token == ledger.review_token
        and not blocking_history_gaps(holding_history_gaps(ledger, as_of=as_of))
    )


def holding_history_gaps(
    ledger: HoldingLedger, *, as_of: date | None = None,
) -> tuple[HoldingHistoryGap, ...]:
    """Explain missing trust, not missing prices or an undefined numerical return."""
    gaps: set[HoldingHistoryGap] = set()
    if not ledger.transactions:
        gaps.add(HoldingHistoryGap.NO_TRANSACTIONS)
    elif not any(txn.type == TransactionType.BUY for txn in ledger.transactions):
        gaps.add(HoldingHistoryGap.NO_ACQUISITION)
    if len(ledger.origins) != len(ledger.transactions) or LedgerOrigin.UNKNOWN in ledger.origins:
        gaps.add(HoldingHistoryGap.UNKNOWN_ORIGIN)
    if LedgerOrigin.SNAPSHOT in ledger.origins:
        gaps.add(HoldingHistoryGap.SNAPSHOT)
    if any(not job.history_complete for job in ledger.imports):
        gaps.add(HoldingHistoryGap.IMPORT_NOT_COMPLETE)
    if any(job.status != ImportStatus.SUCCEEDED for job in ledger.imports):
        gaps.add(HoldingHistoryGap.IMPORT_NOT_SUCCEEDED)
    if ledger.has_unresolved_events:
        gaps.add(HoldingHistoryGap.UNRESOLVED_EVENTS)
    if ledger.has_deleted_transactions:
        gaps.add(HoldingHistoryGap.DELETED_TRANSACTION)
    if ledger.saved_review_token is not None and ledger.saved_review_token != ledger.review_token:
        gaps.add(HoldingHistoryGap.HISTORY_CHANGED)
    try:
        validate_financial_history(ledger.transactions, as_of=as_of)
    except (TransactionDeletionConflict, DecimalException):
        gaps.add(HoldingHistoryGap.INVALID_LEDGER)
    if (
        ledger.review_token is not None and ledger.saved_review_token == ledger.review_token
        and ledger.confirmed_at is not None and not blocking_history_gaps(tuple(gaps))
    ):
        return ()
    return tuple(sorted(gaps))


class TransactionDeletionConflict(ValueError):
    """Deleting this row would violate a ledger or import invariant."""


def validate_share_replay(transactions: Sequence[Transaction]) -> None:
    """Refuse deletions that orphan sales; no quote or FX lookup is necessary.

    Input retains provider order for same-day events. Basis calculations remain
    in the existing FIFO calculator; only share availability is checked here.
    """
    quantity = Decimal(0)
    for txn in sorted(transactions, key=lambda event: event.trade_date):
        if txn.type in (TransactionType.BUY, TransactionType.SELL):
            if not txn.quantity.is_finite() or txn.quantity <= 0:
                raise TransactionDeletionConflict("Remaining trade quantity is invalid")
            quantity += txn.quantity if txn.type == TransactionType.BUY else -txn.quantity
            if quantity < 0:
                raise TransactionDeletionConflict(
                    "Deletion would leave a sale without enough shares; "
                    "remove or correct dependent sales first"
                )
        elif txn.type == TransactionType.SPLIT:
            if not txn.split_ratio.is_finite() or txn.split_ratio <= 0:
                raise TransactionDeletionConflict("Remaining split ratio is invalid")
            quantity *= txn.split_ratio


def validate_financial_history(
    transactions: Sequence[Transaction], *, as_of: date | None = None,
) -> None:
    """Validate the same supported financial facts before confirmation and XIRR."""
    today = as_of or date.today()
    for txn in transactions:
        if txn.type not in tuple(TransactionType):
            raise TransactionDeletionConflict("Ledger contains an unsupported event")
        if txn.trade_date > today or any(
            not value.is_finite() or value < 0
            for value in (txn.quantity, txn.price, txn.fees, txn.amount, txn.split_ratio)
        ):
            raise TransactionDeletionConflict(
                "Ledger contains invalid financial facts or future dates"
            )
    try:
        validate_share_replay(transactions)
    except DecimalException as exc:
        raise TransactionDeletionConflict("Ledger share replay exceeds numeric limits") from exc
