"""Pure confirmation policy and fingerprint sensitivity, without I/O."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.core.currency import FxRateTable
from app.portfolio.history import (
    ACKNOWLEDGEABLE_GAPS,
    blocking_history_gaps,
    confirmation_is_effective,
    history_review_token,
    holding_history_gaps,
)
from app.portfolio.holding_analytics import HoldingAnalyticsService
from app.portfolio.schemas import (
    HistoryImportState,
    HistoryTransactionState,
    HoldingHistoryGap,
    HoldingHistorySnapshot,
    HoldingImportHistory,
    HoldingInfo,
    HoldingLedger,
    HoldingReturnStatus,
    ImportStatus,
    LedgerOrigin,
    PortfolioSummary,
    Transaction,
    TransactionType,
    UnresolvedItem,
    UnresolvedKind,
)
from app.providers.base import HoldingAnalyticsProvider


def purchase() -> Transaction:
    return Transaction(
        ticker="AAA", type=TransactionType.BUY, trade_date=date(2024, 1, 1),
        currency="USD", quantity=Decimal("10"), price=Decimal("100"),
    )


def confirmed_ledger() -> HoldingLedger:
    return HoldingLedger(
        transactions=(purchase(),), origins=(LedgerOrigin.UNKNOWN,),
        review_token="current", saved_review_token="current",
        confirmed_at=datetime(2024, 12, 31, tzinfo=UTC),
    )


@pytest.mark.parametrize("gap", list(HoldingHistoryGap))
def test_only_explicitly_permitted_reasons_are_acknowledgeable(gap: HoldingHistoryGap) -> None:
    assert blocking_history_gaps((gap,)) == (() if gap in ACKNOWLEDGEABLE_GAPS else (gap,))


def test_exact_confirmation_can_acknowledge_unknown_and_deleted_history() -> None:
    ledger = confirmed_ledger().model_copy(update={"has_deleted_transactions": True})
    assert confirmation_is_effective(ledger)
    assert holding_history_gaps(ledger) == ()
    stale = ledger.model_copy(update={"review_token": "new"})
    assert not confirmation_is_effective(stale)
    assert HoldingHistoryGap.HISTORY_CHANGED in holding_history_gaps(stale)


@pytest.mark.parametrize("event", [
    purchase().model_copy(update={"quantity": Decimal("0")}),
    purchase().model_copy(update={"quantity": Decimal("NaN")}),
    purchase().model_copy(update={"price": Decimal("Infinity")}),
    purchase().model_copy(update={"fees": Decimal("-1")}),
    purchase().model_copy(update={"amount": Decimal("-1")}),
    purchase().model_copy(update={"trade_date": date(9999, 1, 1)}),
    purchase().model_copy(update={"type": TransactionType.SELL}),
    purchase().model_copy(update={"type": TransactionType.SPLIT, "split_ratio": Decimal("0")}),
])
def test_invalid_financial_facts_cannot_be_acknowledged(event: Transaction) -> None:
    ledger = confirmed_ledger().model_copy(update={"transactions": (event,)})
    assert not confirmation_is_effective(ledger)
    assert HoldingHistoryGap.INVALID_LEDGER in holding_history_gaps(ledger)


def test_fingerprint_covers_scope_contents_id_origin_ownership_and_tombstones() -> None:
    state = HistoryTransactionState(
        **purchase().model_dump(), id=1, portfolio_id=1,
        history_origin=LedgerOrigin.UNKNOWN, import_job_id=None, deleted_at=None,
    )
    snapshot = HoldingHistorySnapshot(portfolio_id=1, ticker="AAA", transactions=(state,), imports=())
    token = history_review_token(snapshot)
    assert token == history_review_token(snapshot.model_copy(update={"ticker": "aaa"}))
    assert token != history_review_token(snapshot.model_copy(update={"portfolio_id": 2}))
    assert token != history_review_token(snapshot.model_copy(update={"ticker": "BBB"}))
    changed = (
        state.model_copy(update={"id": 2}),
        state.model_copy(update={"price": Decimal("101")}),
        state.model_copy(update={"history_origin": LedgerOrigin.OBSERVED}),
        state.model_copy(update={"import_job_id": 3}),
        state.model_copy(update={"portfolio_id": 2}),
        state.model_copy(update={"deleted_at": datetime(2024, 2, 1, tzinfo=UTC)}),
    )
    for event in changed:
        assert token != history_review_token(snapshot.model_copy(update={"transactions": (event,)}))


async def test_mocked_analytics_uses_effective_confirmation_and_stale_invalidation() -> None:
    provider = AsyncMock(spec=HoldingAnalyticsProvider)
    provider.get_portfolio.return_value = PortfolioSummary(id=1, name="Test", base_currency="USD")
    provider.get_holding.return_value = HoldingInfo(ticker="AAA")
    provider.get_holding_ledger.return_value = confirmed_ledger()
    service = HoldingAnalyticsService(provider, FxRateTable(base_currency="USD"))
    result = await service.get_analytics(1, "aaa", as_of=date(2024, 12, 31))
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == HoldingReturnStatus.UNPRICED_POSITION
    provider.get_holding_ledger.return_value = confirmed_ledger().model_copy(update={
        "review_token": "changed",
    })
    result = await service.get_analytics(1, "aaa", as_of=date(2024, 12, 31))
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == HoldingReturnStatus.INCOMPLETE_HISTORY


@pytest.mark.parametrize("ledger", [
    confirmed_ledger().model_copy(update={"transactions": (), "origins": ()}),
    confirmed_ledger().model_copy(update={"origins": (LedgerOrigin.SNAPSHOT,)}),
    confirmed_ledger().model_copy(update={"has_unresolved_events": True}),
    *(confirmed_ledger().model_copy(update={"imports": (HoldingImportHistory(
        status=status, history_complete=True,
    ),)}) for status in (ImportStatus.PENDING, ImportStatus.RUNNING, ImportStatus.FAILED)),
    confirmed_ledger().model_copy(update={"transactions": (purchase().model_copy(update={
        "type": TransactionType.DIVIDEND,
    }),)}),
])
def test_saved_confirmation_never_overrides_hard_blockers(ledger: HoldingLedger) -> None:
    assert blocking_history_gaps(holding_history_gaps(ledger))
    assert not confirmation_is_effective(ledger)


def test_import_fingerprint_covers_status_completeness_ownership_and_unresolved_facts() -> None:
    item = UnresolvedItem(
        id=1, import_id=2, portfolio_id=1, kind=UnresolvedKind.UNSUPPORTED_ROW,
        source_line=3, ticker="AAA", quantity=Decimal("2"), resolved=False,
    )
    job = HistoryImportState(
        id=2, portfolio_id=1, status=ImportStatus.SUCCEEDED, history_complete=False,
        tickers=("BBB", "AAA"), unresolved_items=(item,),
    )
    snapshot = HoldingHistorySnapshot(portfolio_id=1, ticker="AAA", transactions=(), imports=(job,))
    token = history_review_token(snapshot)
    assert token == history_review_token(snapshot.model_copy(update={"imports": (
        job.model_copy(update={"tickers": ("aaa", "bbb")}),
    )}))
    changes = (
        job.model_copy(update={"id": 3}),
        job.model_copy(update={"portfolio_id": 2}),
        job.model_copy(update={"status": ImportStatus.FAILED}),
        job.model_copy(update={"history_complete": True}),
        job.model_copy(update={"tickers": ("AAA",)}),
        *(job.model_copy(update={"unresolved_items": (item.model_copy(update=update),)})
          for update in ({"resolved": True}, {"quantity": Decimal("3")},
                         {"ticker": None}, {"source_line": 4})),
    )
    for changed in changes:
        assert token != history_review_token(snapshot.model_copy(update={"imports": (changed,)}))


async def test_confirmed_incomplete_import_allows_closed_xirr_without_market_data() -> None:
    provider = AsyncMock(spec=HoldingAnalyticsProvider)
    provider.get_portfolio.return_value = PortfolioSummary(id=1, name="Test", base_currency="USD")
    provider.get_holding.return_value = HoldingInfo(ticker="AAA")
    provider.get_holding_ledger.return_value = confirmed_ledger().model_copy(update={
        "transactions": (purchase(), purchase().model_copy(update={
            "type": TransactionType.SELL, "trade_date": date(2024, 12, 31),
            "price": Decimal("110"),
        })),
        "origins": (LedgerOrigin.UNKNOWN, LedgerOrigin.OBSERVED),
        "imports": (HoldingImportHistory(status=ImportStatus.SUCCEEDED, history_complete=False),),
    })
    result = await HoldingAnalyticsService(provider, FxRateTable(base_currency="USD")).get_analytics(
        1, "AAA", as_of=date(2024, 12, 31),
    )
    assert result is not None and result.money_weighted_return_status == HoldingReturnStatus.OK
    assert result.money_weighted_return is not None
    assert abs(result.money_weighted_return - Decimal("0.1")) < Decimal("0.0001")
