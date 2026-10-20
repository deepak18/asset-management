from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.core.currency import FxRate, FxRateTable
from app.marketdata.errors import MarketDataUnavailableError
from app.marketdata.schemas import MarketDataProvenance, Quote
from app.portfolio.holding_analytics import HoldingAnalyticsService
from app.portfolio.schemas import (
    HoldingImportHistory,
    HoldingInfo,
    HoldingLedger,
    HoldingReturnStatus,
    HoldingValuationSource,
    ImportStatus,
    LedgerOrigin,
    PortfolioSummary,
    Transaction,
    TransactionType,
)
from app.providers.base import HoldingAnalyticsProvider
from app.providers.marketdata_provider import MarketDataProvider

START = date(2024, 1, 1)
END = date(2024, 12, 31)  # exactly 365 days


def event(kind: TransactionType = TransactionType.BUY, **changes: object) -> Transaction:
    return Transaction.model_validate({
        "ticker": "AAA", "type": kind, "trade_date": START,
        "currency": "USD", "quantity": "10", "price": "100", **changes,
    })


def ledger(*events: Transaction) -> HoldingLedger:
    return HoldingLedger(
        transactions=events, origins=tuple(LedgerOrigin.OBSERVED for _ in events),
    )


def dependencies(history: HoldingLedger) -> tuple[AsyncMock, AsyncMock]:
    reader = AsyncMock(spec=HoldingAnalyticsProvider)
    reader.get_portfolio.return_value = PortfolioSummary(id=1, name="Test", base_currency="USD")
    reader.get_holding.return_value = HoldingInfo(ticker="AAA")
    reader.get_holding_ledger.return_value = history
    market = AsyncMock(spec=MarketDataProvider)
    market.get_quote.return_value = Quote(
        ticker="AAA", price=Decimal("110"), currency="USD",
        provenance=MarketDataProvenance(
            provider_code="TEST", source_table="QUOTE", as_of=datetime(2024, 12, 30, tzinfo=UTC),
        ),
    )
    return reader, market


@pytest.mark.asyncio
async def test_open_return_and_quote_citation() -> None:
    reader, market = dependencies(ledger(event()))
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "aaa", as_of=END)
    assert result is not None
    assert result.money_weighted_return_status == HoldingReturnStatus.OK
    assert float(result.money_weighted_return) == pytest.approx(.1)  # type: ignore[arg-type]
    assert result.valuation_source == HoldingValuationSource.QUOTE
    assert result.valuation_date == END
    assert result.valuation_provenance == market.get_quote.return_value.provenance
    assert result.valuation_provenance.as_of.date() == date(2024, 12, 30)
    market.get_quote.assert_awaited_once_with("AAA")
    reader.get_holding_ledger.assert_awaited_once_with(1, "AAA")


@pytest.mark.asyncio
async def test_partial_sell_dividend_fees_and_split() -> None:
    history = ledger(
        event(fees="10"),
        event(TransactionType.SPLIT, trade_date=END, split_ratio="2"),
        event(TransactionType.SELL, trade_date=END, quantity="5", price="60", fees="2"),
        event(TransactionType.DIVIDEND, trade_date=END, amount="20"),
        event(TransactionType.FEE, trade_date=END, amount="5"),
    )
    reader, market = dependencies(history)
    market.get_quote.return_value = market.get_quote.return_value.model_copy(
        update={"price": Decimal("60")}
    )
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "AAA", as_of=END)
    assert result is not None and result.money_weighted_return is not None
    # 20 split-adjusted shares minus 5 sold: terminal 900; net sale 298.
    assert float(result.money_weighted_return) == pytest.approx((900 + 298 + 20 - 5) / 1010 - 1)


@pytest.mark.asyncio
async def test_closed_position_needs_no_quote_or_terminal_value() -> None:
    reader, market = dependencies(ledger(
        event(), event(TransactionType.SELL, trade_date=END, price="110"),
    ))
    market.get_quote.side_effect = AssertionError("closed positions must not request quotes")
    for provider in (None, market):
        result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), provider
                                              ).get_analytics(1, "AAA", as_of=date(2025, 1, 1))
        assert result is not None and result.money_weighted_return is not None
        assert float(result.money_weighted_return) == pytest.approx(.1)
        assert result.valuation_date == END
        assert result.valuation_source == HoldingValuationSource.LEDGER
        assert result.valuation_provenance is None
    market.get_quote.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", [LedgerOrigin.SNAPSHOT, LedgerOrigin.UNKNOWN])
async def test_unobserved_history_withheld_even_after_closing(origin: LedgerOrigin) -> None:
    history = ledger(event(), event(TransactionType.SELL, trade_date=END))
    history = history.model_copy(update={"origins": (origin, LedgerOrigin.OBSERVED)})
    reader, market = dependencies(history)
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "AAA", as_of=END)
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == HoldingReturnStatus.INCOMPLETE_HISTORY
    market.get_quote.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,complete", [
    (ImportStatus.SUCCEEDED, False), (ImportStatus.FAILED, True),
    (ImportStatus.PENDING, True), (ImportStatus.RUNNING, True),
])
async def test_import_history_must_be_complete_and_succeeded(
    status: ImportStatus, complete: bool,
) -> None:
    history = ledger(event()).model_copy(update={
        "imports": (HoldingImportHistory(status=status, history_complete=complete),),
    })
    reader, market = dependencies(history)
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "AAA", as_of=END)
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == HoldingReturnStatus.INCOMPLETE_HISTORY
    market.get_quote.assert_not_awaited()


@pytest.mark.asyncio
async def test_unresolved_events_withhold_return() -> None:
    reader, market = dependencies(ledger(event()).model_copy(update={"has_unresolved_events": True}))
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "AAA", as_of=END)
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == HoldingReturnStatus.INCOMPLETE_HISTORY


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["disabled", "missing", "outage", "negative", "wrong_ticker", "future"])
async def test_unavailable_prices(mode: str) -> None:
    reader, market = dependencies(ledger(event()))
    if mode == "missing":
        market.get_quote.return_value = None
    elif mode == "outage":
        market.get_quote.side_effect = MarketDataUnavailableError("quota")
    elif mode in {"negative", "wrong_ticker", "future"}:
        changes = {
            "negative": {"price": Decimal("-1")},
            "wrong_ticker": {"ticker": "OTHER"},
            "future": {"provenance": MarketDataProvenance(
                provider_code="TEST", source_table="QUOTE", as_of=datetime(2025, 1, 1, tzinfo=UTC),
            )},
        }
        market.get_quote.return_value = market.get_quote.return_value.model_copy(update=changes[mode])
    result = await HoldingAnalyticsService(
        reader, FxRateTable(base_currency="USD"), None if mode == "disabled" else market,
    ).get_analytics(1, "AAA", as_of=END)
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == HoldingReturnStatus.UNPRICED_POSITION


@pytest.mark.asyncio
@pytest.mark.parametrize("quote_fx", [True, False])
async def test_missing_trade_or_quote_fx(quote_fx: bool) -> None:
    reader, market = dependencies(ledger(event(currency="USD" if quote_fx else "EUR")))
    if quote_fx:
        market.get_quote.return_value = market.get_quote.return_value.model_copy(update={"currency": "EUR"})
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "AAA", as_of=END)
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == HoldingReturnStatus.MISSING_FX


@pytest.mark.asyncio
async def test_dated_fx_is_applied_to_flows_and_terminal_value() -> None:
    reader, market = dependencies(ledger(event(currency="EUR")))
    market.get_quote.return_value = market.get_quote.return_value.model_copy(update={"currency": "EUR"})
    fx = FxRateTable(base_currency="USD", rates=(
        FxRate(currency="EUR", as_of=START, rate_to_base=Decimal("1.1")),
        FxRate(currency="EUR", as_of=END, rate_to_base=Decimal("1.2")),
    ))
    result = await HoldingAnalyticsService(reader, fx, market).get_analytics(1, "AAA", as_of=END)
    assert result is not None and result.money_weighted_return is not None
    assert float(result.money_weighted_return) == pytest.approx(1320 / 1100 - 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("events,expected", [
    ((), HoldingReturnStatus.INSUFFICIENT_FLOWS),
    ((event(trade_date=END),), HoldingReturnStatus.INSUFFICIENT_FLOWS),
    ((event(trade_date=date(2025, 1, 1)),), HoldingReturnStatus.INVALID_HISTORY),
    ((event(TransactionType.SELL),), HoldingReturnStatus.INVALID_HISTORY),
])
async def test_undefined_or_invalid_history(
    events: tuple[Transaction, ...], expected: HoldingReturnStatus,
) -> None:
    reader, market = dependencies(ledger(*events))
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "AAA", as_of=END)
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["portfolio", "holding"])
async def test_missing_identity(missing: str) -> None:
    reader, market = dependencies(ledger(event()))
    getattr(reader, f"get_{missing}").return_value = None
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "AAA", as_of=END)
    assert result is None
    reader.get_holding_ledger.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_zero_return_is_a_number_not_unavailable() -> None:
    reader, market = dependencies(ledger(event(), event(TransactionType.SELL, trade_date=END)))
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "AAA", as_of=END)
    assert result is not None
    assert result.money_weighted_return_status == HoldingReturnStatus.OK
    assert result.money_weighted_return is not None
    assert abs(result.money_weighted_return) < Decimal("0.000000001")


@pytest.mark.asyncio
async def test_reporting_currency_comes_from_portfolio_not_global_settings() -> None:
    reader, market = dependencies(ledger(event(currency="EUR")))
    reader.get_portfolio.return_value = PortfolioSummary(id=1, name="Euro", base_currency="EUR")
    market.get_quote.return_value = market.get_quote.return_value.model_copy(update={"currency": "EUR"})
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "AAA", as_of=END)
    assert result is not None and result.money_weighted_return is not None
    assert result.base_currency == "EUR"
    assert float(result.money_weighted_return) == pytest.approx(.1)


@pytest.mark.asyncio
async def test_dividends_and_fees_without_acquisition_are_incomplete() -> None:
    reader, market = dependencies(ledger(
        event(TransactionType.FEE, amount="50"),
        event(TransactionType.DIVIDEND, trade_date=END, amount="100"),
    ))
    result = await HoldingAnalyticsService(reader, FxRateTable(base_currency="USD"), market
                                          ).get_analytics(1, "AAA", as_of=END)
    assert result is not None and result.money_weighted_return is None
    assert result.money_weighted_return_status == HoldingReturnStatus.INCOMPLETE_HISTORY
    market.get_quote.assert_not_awaited()
