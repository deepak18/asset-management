from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency import FxRateTable
from app.portfolio.holding_analytics import HoldingAnalyticsService
from app.portfolio.ingest import PortfolioIngestService
from app.portfolio.reconciliation import correction_transaction
from app.portfolio.schemas import (
    HoldingReturnStatus,
    ImportIssue,
    LedgerOrigin,
    PortfolioCreate,
    PositionSnapshot,
    Transaction,
    TransactionType,
    UnresolvedKind,
    UnresolvedResolution,
)
from app.providers.marketdata_provider import MarketDataProvider
from app.providers.portfolio_provider import SqlAlchemyPortfolioProvider
from app.providers.statement_import_store import SqlAlchemyStatementImportStore


def buy(ticker: str = "AAA") -> Transaction:
    return Transaction(
        ticker=ticker, type=TransactionType.BUY, trade_date=date(2024, 1, 1),
        currency="USD", quantity=Decimal("10"), price=Decimal("100"),
    )


async def test_snapshot_origin_survives_direct_and_repair_writes(async_session: AsyncSession) -> None:
    provider = SqlAlchemyPortfolioProvider(async_session)
    summary = await provider.create_portfolio(PortfolioCreate(name="History", base_currency="USD"))
    snapshot = PositionSnapshot(
        ticker="AAA", quantity=Decimal("10"), total_cost_basis=Decimal("1000"),
        currency="USD", as_of=date(2024, 1, 1),
    )
    await PortfolioIngestService(provider, provider).add_snapshots(summary.id, [snapshot])
    assert (await provider.get_holding_ledger(summary.id, "aaa")).origins == (LedgerOrigin.SNAPSHOT,)
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(summary.id, "robinhood_csv", "rh.csv", "key", "a" * 64, 1, True)
    await store.mark_succeeded(job.id, 0, [], [], [ImportIssue(
        kind=UnresolvedKind.TRANSFER_IN_NO_COST_BASIS, source_line=2, ticker="BBB",
        trade_date=date(2024, 1, 1), currency="USD", quantity=Decimal("10"),
    )])
    issues = await store.list_unresolved(summary.id)
    repaired = correction_transaction(issues[0], UnresolvedResolution(
        snapshot=snapshot.model_copy(update={"ticker": "BBB"}),
    ))
    await store.resolve_item(summary.id, issues[0].id, repaired)
    history = await provider.get_holding_ledger(summary.id, "BBB")
    assert history.origins == (LedgerOrigin.SNAPSHOT,)
    assert not history.has_unresolved_events
    service = HoldingAnalyticsService(provider, FxRateTable(base_currency="USD"))
    for ticker in ("AAA", "BBB"):
        holding = await provider.get_holding(summary.id, ticker)
        assert holding is not None and not holding.history_complete
        assert "SNAPSHOT" in holding.history_gaps
        result = await service.get_analytics(summary.id, ticker, as_of=date(2024, 12, 31))
        assert result is not None and result.money_weighted_return is None
        assert result.money_weighted_return_status == HoldingReturnStatus.INCOMPLETE_HISTORY


@pytest.mark.parametrize("complete", [False, True])
async def test_only_relevant_import_history_blocks_closed_ticker(
    async_session: AsyncSession, complete: bool,
) -> None:
    provider = SqlAlchemyPortfolioProvider(async_session)
    summary = await provider.create_portfolio(PortfolioCreate(name="History", base_currency="USD"))
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(summary.id, "robinhood_csv", "rh.csv", "key", "a" * 64, 1, complete)
    assert await store.claim_job(job.id)
    await store.append_batch(job.id, [buy(), buy("OTHER")])
    await store.mark_succeeded(job.id, 2, ["AAA", "OTHER"], [])
    # A separate incomplete import for OTHER must not leak into AAA history.
    other = await store.create_job(summary.id, "robinhood_csv", "other.csv", "key2", "b" * 64, 1)
    assert await store.claim_job(other.id)
    await store.append_batch(other.id, [buy("OTHER")])
    await store.mark_succeeded(other.id, 1, ["OTHER"], [])
    await provider.add_transactions(summary.id, [buy().model_copy(update={
        "type": TransactionType.SELL, "trade_date": date(2024, 12, 31), "price": Decimal("110"),
    })])
    history = await provider.get_holding_ledger(summary.id, "AAA")
    assert len(history.transactions) == 2
    assert len(history.imports) == 1
    assert history.imports[0].history_complete == complete
    holding = await provider.get_holding(summary.id, "AAA")
    assert holding is not None and holding.history_complete == complete
    assert holding.history_gaps == (() if complete else ("IMPORT_NOT_COMPLETE",))
    market = AsyncMock(spec=MarketDataProvider)
    result = await HoldingAnalyticsService(provider, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(summary.id, "AAA", as_of=date(2024, 12, 31))
    assert result is not None
    if complete:
        assert result.money_weighted_return is not None
        assert float(result.money_weighted_return) == pytest.approx(.1)
    else:
        assert result.money_weighted_return is None
        assert result.money_weighted_return_status == HoldingReturnStatus.INCOMPLETE_HISTORY
    market.get_quote.assert_not_awaited()


@pytest.mark.parametrize("issue_ticker,blocks", [("AAA", True), (None, True), ("OTHER", False)])
async def test_unresolved_event_scoping(
    async_session: AsyncSession, issue_ticker: str | None, blocks: bool,
) -> None:
    provider = SqlAlchemyPortfolioProvider(async_session)
    summary = await provider.create_portfolio(PortfolioCreate(name="History", base_currency="USD"))
    await provider.add_transactions(summary.id, [buy()])
    await provider.upsert_holding(summary.id, "AAA")
    store = SqlAlchemyStatementImportStore(async_session)
    job = await store.create_job(summary.id, "robinhood_csv", "rh.csv", "key", "a" * 64, 1, True)
    await store.mark_succeeded(job.id, 0, [], [], [ImportIssue(
        kind=UnresolvedKind.UNSUPPORTED_ROW, source_line=2, ticker=issue_ticker,
    )])
    history = await provider.get_holding_ledger(summary.id, "AAA")
    assert history.has_unresolved_events == blocks
    holding = await provider.get_holding(summary.id, "AAA")
    assert holding is not None and holding.history_complete == (not blocks)
    assert ("UNRESOLVED_EVENTS" in holding.history_gaps) == blocks


async def test_unfinished_unassigned_import_is_conservatively_incomplete(
    async_session: AsyncSession,
) -> None:
    provider = SqlAlchemyPortfolioProvider(async_session)
    summary = await provider.create_portfolio(PortfolioCreate(name="History", base_currency="USD"))
    await provider.add_transactions(summary.id, [buy()])
    await provider.upsert_holding(summary.id, "AAA")
    store = SqlAlchemyStatementImportStore(async_session)
    await store.create_job(summary.id, "robinhood_csv", "rh.csv", "key", "a" * 64, 1, True)
    result = await HoldingAnalyticsService(provider, FxRateTable(base_currency="USD")
                                          ).get_analytics(summary.id, "AAA", as_of=date(2024, 12, 31))
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == HoldingReturnStatus.INCOMPLETE_HISTORY
