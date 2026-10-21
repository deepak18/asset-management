"""Pure history diagnostics shared by holding reads and return orchestration."""

from collections.abc import Sequence
from decimal import Decimal

from app.portfolio.schemas import (
    HoldingHistoryGap,
    HoldingLedger,
    ImportStatus,
    LedgerOrigin,
    Transaction,
    TransactionType,
)


def holding_history_gaps(ledger: HoldingLedger) -> tuple[HoldingHistoryGap, ...]:
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
