from datetime import date
from decimal import Decimal

import pytest

from app.portfolio.history import (
    TransactionDeletionConflict,
    holding_history_gaps,
    validate_share_replay,
)
from app.portfolio.schemas import (
    HoldingHistoryGap,
    HoldingImportHistory,
    HoldingLedger,
    ImportStatus,
    LedgerOrigin,
    Transaction,
    TransactionType,
)


def event(kind: TransactionType = TransactionType.BUY, quantity: str = "10") -> Transaction:
    return Transaction(
        ticker="AAA", type=kind, trade_date=date(2024, 1, 1), currency="USD",
        quantity=Decimal(quantity), price=Decimal("100"),
    )


def observed() -> HoldingLedger:
    return HoldingLedger(transactions=(event(),), origins=(LedgerOrigin.OBSERVED,))


def test_observed_acquisition_is_complete_without_prices_or_classification() -> None:
    assert holding_history_gaps(observed()) == ()


@pytest.mark.parametrize("ledger,expected", [
    (HoldingLedger(), HoldingHistoryGap.NO_TRANSACTIONS),
    (HoldingLedger(transactions=(event(TransactionType.DIVIDEND),), origins=(LedgerOrigin.OBSERVED,)), HoldingHistoryGap.NO_ACQUISITION),
    (observed().model_copy(update={"origins": (LedgerOrigin.UNKNOWN,)}), HoldingHistoryGap.UNKNOWN_ORIGIN),
    (observed().model_copy(update={"origins": ()}), HoldingHistoryGap.UNKNOWN_ORIGIN),
    (observed().model_copy(update={"origins": (LedgerOrigin.SNAPSHOT,)}), HoldingHistoryGap.SNAPSHOT),
    (observed().model_copy(update={"has_unresolved_events": True}), HoldingHistoryGap.UNRESOLVED_EVENTS),
    (observed().model_copy(update={"has_deleted_transactions": True}), HoldingHistoryGap.DELETED_TRANSACTION),
    (observed().model_copy(update={"imports": (HoldingImportHistory(status=ImportStatus.SUCCEEDED, history_complete=False),)}), HoldingHistoryGap.IMPORT_NOT_COMPLETE),
    (observed().model_copy(update={"imports": (HoldingImportHistory(status=ImportStatus.RUNNING, history_complete=True),)}), HoldingHistoryGap.IMPORT_NOT_SUCCEEDED),
])
def test_specific_history_reason(ledger: HoldingLedger, expected: HoldingHistoryGap) -> None:
    assert holding_history_gaps(ledger) == (expected,)


def test_multiple_reasons_are_sorted_and_not_collapsed_to_snapshot() -> None:
    gaps = holding_history_gaps(observed().model_copy(update={
        "origins": (LedgerOrigin.UNKNOWN,), "has_deleted_transactions": True,
        "imports": (HoldingImportHistory(status=ImportStatus.FAILED, history_complete=False),),
    }))
    assert gaps == tuple(sorted({
        HoldingHistoryGap.UNKNOWN_ORIGIN, HoldingHistoryGap.DELETED_TRANSACTION,
        HoldingHistoryGap.IMPORT_NOT_COMPLETE, HoldingHistoryGap.IMPORT_NOT_SUCCEEDED,
    }))
    assert HoldingHistoryGap.SNAPSHOT not in gaps


def test_share_replay_accounts_for_splits_and_partial_sales() -> None:
    split = event(TransactionType.SPLIT).model_copy(update={"split_ratio": Decimal("2")})
    validate_share_replay([event(), split, event(TransactionType.SELL, "15")])
    with pytest.raises(TransactionDeletionConflict, match="without enough shares"):
        validate_share_replay([event(), event(TransactionType.SELL, "15")])


@pytest.mark.parametrize("events", [
    [event(TransactionType.SELL)],
    [event(quantity="0")],
    [event(), event(TransactionType.SPLIT).model_copy(update={"split_ratio": Decimal("0")})],
])
def test_invalid_remaining_share_history_is_refused(events: list[Transaction]) -> None:
    with pytest.raises(TransactionDeletionConflict):
        validate_share_replay(events)
