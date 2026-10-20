"""Unit tests for :class:`PortfolioService` orchestration.

The provider boundary is faked in-memory — no DB, no network — so we test only
the service's coordination logic: grouping, roll-up totals, XIRR wiring, and the
missing-portfolio path. Financial correctness itself is covered by the calculator
tests; here we assert the service *assembles* those results correctly.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.currency import FxRateTable
from app.marketdata.errors import MarketDataUnavailableError
from app.marketdata.schemas import MarketDataProvenance, Quote
from app.portfolio.schemas import (
    ClassificationSource,
    DataGap,
    HoldingInfo,
    MoneyWeightedReturnStatus,
    PortfolioSummary,
    Transaction,
    TransactionType,
)
from app.portfolio.service import PortfolioService


class FakePortfolioProvider:
    """Structural stand-in for PortfolioProvider backed by in-memory lists."""

    def __init__(
        self,
        summary: PortfolioSummary | None,
        transactions: list[Transaction] | None = None,
        holdings: list[HoldingInfo] | None = None,
    ) -> None:
        self._summary = summary
        self._transactions = transactions or []
        self._holdings = holdings or []

    async def get_portfolio(self, portfolio_id: int) -> PortfolioSummary | None:
        return self._summary

    async def list_portfolios(self) -> list[PortfolioSummary]:
        return [self._summary] if self._summary is not None else []

    async def list_transactions(self, portfolio_id: int) -> list[Transaction]:
        return self._transactions

    async def list_holdings(self, portfolio_id: int) -> list[HoldingInfo]:
        return self._holdings

    async def get_holding(self, portfolio_id: int, ticker: str) -> HoldingInfo | None:
        return next((h for h in self._holdings if h.ticker == ticker.upper()), None)


class FakeMarketData:
    """Structural stand-in for MarketDataProvider with canned prices."""

    def __init__(
        self, prices: dict[str, Decimal], *, unavailable: set[str] | None = None
    ) -> None:
        self._prices = prices
        self._unavailable = unavailable or set()

    async def get_quote(self, ticker: str) -> Quote | None:
        if ticker in self._unavailable:
            raise MarketDataUnavailableError("upstream down")
        price = self._prices.get(ticker)
        if price is None:
            return None
        return Quote(
            ticker=ticker,
            price=price,
            currency="USD",
            provenance=MarketDataProvenance(
                provider_code="ALPHAVANTAGE",
                source_table="GLOBAL_QUOTE",
                as_of=datetime(2026, 7, 26, tzinfo=UTC),
            ),
        )

    async def get_company_profile(self, ticker: str) -> None:
        return None

    async def get_financial_statements(self, ticker: str, statement_type: object) -> None:
        return None


def _txn(
    type_: TransactionType, month: int, day: int, *, ticker: str = "AAPL", **kwargs: Decimal
) -> Transaction:
    return Transaction(
        ticker=ticker,
        type=type_,
        trade_date=date(2026, month, day),
        currency="USD",
        **kwargs,
    )


async def test_missing_portfolio_returns_none(usd_only_fx: FxRateTable) -> None:
    service = PortfolioService(FakePortfolioProvider(summary=None), usd_only_fx)
    assert await service.get_analytics(1) is None


async def test_empty_ledger_yields_zeroed_totals(usd_only_fx: FxRateTable) -> None:
    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    service = PortfolioService(FakePortfolioProvider(summary, transactions=[]), usd_only_fx)

    analytics = await service.get_analytics(1)

    assert analytics is not None
    assert analytics.positions == ()
    assert analytics.realized_pnl_base == Decimal(0)
    assert analytics.open_cost_basis_base == Decimal(0)
    # XIRR is undefined for an empty ledger -> reported honestly as None.
    assert analytics.money_weighted_return is None
    assert (
        analytics.money_weighted_return_status
        is MoneyWeightedReturnStatus.INSUFFICIENT_FLOWS
    )


async def test_rolls_up_realized_pnl_and_open_cost(usd_only_fx: FxRateTable) -> None:
    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    transactions = [
        _txn(TransactionType.BUY, 1, 1, quantity=Decimal("10"), price=Decimal("100")),
        _txn(TransactionType.SELL, 3, 1, quantity=Decimal("4"), price=Decimal("150")),
    ]
    service = PortfolioService(
        FakePortfolioProvider(summary, transactions=transactions), usd_only_fx
    )

    analytics = await service.get_analytics(1)

    assert analytics is not None
    # Bought 10@100, sold 4@150 -> realized 4*(150-100)=200; 6 open @100 = 600.
    assert analytics.realized_pnl_base == Decimal("200")
    assert analytics.open_cost_basis_base == Decimal("600")
    assert len(analytics.positions) == 1
    assert analytics.positions[0].ticker == "AAPL"
    # 6 shares are still held and nothing can price them, so the terminal value is
    # unknown. A return computed without it would ignore most of the capital, so
    # it is withheld with an explicit reason rather than reported as a number.
    assert analytics.money_weighted_return is None
    assert (
        analytics.money_weighted_return_status
        is MoneyWeightedReturnStatus.UNPRICED_POSITIONS
    )


async def test_fully_closed_book_needs_no_terminal_value(usd_only_fx: FxRateTable) -> None:
    """With nothing left open, the flows alone already change sign."""

    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    transactions = [
        _txn(TransactionType.BUY, 1, 1, quantity=Decimal("10"), price=Decimal("100")),
        _txn(TransactionType.SELL, 7, 1, quantity=Decimal("10"), price=Decimal("110")),
    ]
    service = PortfolioService(FakePortfolioProvider(summary, transactions), usd_only_fx)

    analytics = await service.get_analytics(1)

    assert analytics is not None
    assert analytics.money_weighted_return_status is MoneyWeightedReturnStatus.OK
    assert analytics.money_weighted_return is not None
    # Bought at 100, sold at 110 roughly half a year later -> strongly positive.
    assert analytics.money_weighted_return > Decimal("0")
    assert analytics.unpriced_tickers == ()


async def test_terminal_market_value_makes_buy_only_xirr_computable(
    usd_only_fx: FxRateTable,
) -> None:
    """A buy-only ledger has one-sign flows; today's market value supplies the other.

    This is the case that matters for a real imported statement: without the
    synthetic liquidation inflow there is no root to solve for at all.
    """

    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    # Two dated buys, no sells -> every flow is negative on its own.
    transactions = [
        _txn(TransactionType.BUY, 1, 1, quantity=Decimal("10"), price=Decimal("100")),
        _txn(TransactionType.BUY, 3, 1, quantity=Decimal("10"), price=Decimal("110")),
    ]
    market = FakeMarketData({"AAPL": Decimal("150")})
    service = PortfolioService(FakePortfolioProvider(summary, transactions), usd_only_fx, market)

    analytics = await service.get_analytics(1)

    assert analytics is not None
    assert analytics.money_weighted_return_status is MoneyWeightedReturnStatus.OK
    assert analytics.money_weighted_return is not None
    # Paid 2100 for 20 shares now worth 3000 -> the return must be positive.
    assert analytics.money_weighted_return > Decimal("0")


async def test_partially_priced_book_withholds_the_return(usd_only_fx: FxRateTable) -> None:
    """One missing price makes the terminal value partial -> no number, with a reason."""

    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    transactions = [
        _txn(TransactionType.BUY, 1, 1, ticker="AAPL", quantity=Decimal("10"), price=Decimal("100")),
        _txn(TransactionType.BUY, 1, 1, ticker="MSFT", quantity=Decimal("5"), price=Decimal("200")),
    ]
    market = FakeMarketData({"AAPL": Decimal("150")})  # MSFT unpriced
    service = PortfolioService(FakePortfolioProvider(summary, transactions), usd_only_fx, market)

    analytics = await service.get_analytics(1)

    assert analytics is not None
    assert analytics.unpriced_tickers == ("MSFT",)
    assert analytics.money_weighted_return is None
    assert (
        analytics.money_weighted_return_status
        is MoneyWeightedReturnStatus.UNPRICED_POSITIONS
    )


async def test_positions_are_grouped_per_ticker_and_sorted(usd_only_fx: FxRateTable) -> None:
    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    transactions = [
        _txn(TransactionType.BUY, 1, 1, ticker="MSFT", quantity=Decimal("5"), price=Decimal("200")),
        _txn(TransactionType.BUY, 1, 1, ticker="AAPL", quantity=Decimal("10"), price=Decimal("100")),
    ]
    service = PortfolioService(
        FakePortfolioProvider(summary, transactions=transactions), usd_only_fx
    )

    analytics = await service.get_analytics(1)

    assert analytics is not None
    assert [p.ticker for p in analytics.positions] == ["AAPL", "MSFT"]
    assert analytics.open_cost_basis_base == Decimal("2000")  # 1000 + 1000


async def test_without_market_data_market_fields_are_empty(usd_only_fx: FxRateTable) -> None:
    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    transactions = [_txn(TransactionType.BUY, 1, 1, quantity=Decimal("10"), price=Decimal("100"))]
    service = PortfolioService(FakePortfolioProvider(summary, transactions), usd_only_fx)

    analytics = await service.get_analytics(1)

    assert analytics is not None
    # No provider → market-value analytics degrade to empty/None (offline-safe).
    assert analytics.market_value_base is None
    assert analytics.unrealized_pnl_base is None
    assert analytics.positions_unrealized == ()
    assert analytics.allocation_by_ticker == ()
    assert analytics.unpriced_tickers == ("AAPL",)


async def test_market_values_and_allocations_are_computed(usd_only_fx: FxRateTable) -> None:
    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    transactions = [
        _txn(TransactionType.BUY, 1, 1, ticker="AAPL", quantity=Decimal("10"), price=Decimal("100")),
        _txn(TransactionType.BUY, 1, 1, ticker="MSFT", quantity=Decimal("5"), price=Decimal("200")),
    ]
    holdings = [
        HoldingInfo(ticker="AAPL", sector="Tech", industry="Hardware"),
        HoldingInfo(ticker="MSFT", sector="Tech", industry="Software"),
    ]
    market = FakeMarketData({"AAPL": Decimal("150"), "MSFT": Decimal("250")})
    service = PortfolioService(
        FakePortfolioProvider(summary, transactions, holdings), usd_only_fx, market
    )

    analytics = await service.get_analytics(1)

    assert analytics is not None
    # AAPL 10@100→mv 1500 (+500); MSFT 5@200→mv 1250 (+250).
    assert analytics.market_value_base == Decimal("2750")
    assert analytics.unrealized_pnl_base == Decimal("750")
    assert len(analytics.positions_unrealized) == 2
    by_ticker = {r.key: r for r in analytics.allocation_by_ticker}
    assert by_ticker["AAPL"].market_value == Decimal("1500")
    # Both tickers roll up under one sector, so its weight is the whole book.
    by_sector = {r.key: r for r in analytics.allocation_by_sector}
    assert by_sector["Tech"].market_value == Decimal("2750")
    assert by_sector["Tech"].weight == Decimal("1")
    assert analytics.unpriced_tickers == ()
    assert analytics.priced_as_of is not None


async def test_unpriced_ticker_is_reported_not_faked(usd_only_fx: FxRateTable) -> None:
    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    transactions = [_txn(TransactionType.BUY, 1, 1, quantity=Decimal("10"), price=Decimal("100"))]
    market = FakeMarketData({})  # no price for AAPL
    service = PortfolioService(FakePortfolioProvider(summary, transactions), usd_only_fx, market)

    analytics = await service.get_analytics(1)

    assert analytics is not None
    assert analytics.market_value_base is None
    assert analytics.allocation_by_ticker == ()
    assert analytics.unpriced_tickers == ("AAPL",)


async def test_market_data_unavailable_degrades_to_unpriced(usd_only_fx: FxRateTable) -> None:
    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    transactions = [_txn(TransactionType.BUY, 1, 1, quantity=Decimal("10"), price=Decimal("100"))]
    market = FakeMarketData({}, unavailable={"AAPL"})
    service = PortfolioService(FakePortfolioProvider(summary, transactions), usd_only_fx, market)

    analytics = await service.get_analytics(1)

    assert analytics is not None
    # A rate-limited/unreachable upstream must not 500 the analytics call.
    assert analytics.unpriced_tickers == ("AAPL",)
    assert analytics.market_value_base is None


async def test_position_gaps_are_user_fixable_not_missing_prices(usd_only_fx: FxRateTable) -> None:
    summary = PortfolioSummary(id=1, name="Main", base_currency="USD")
    transactions = [_txn(TransactionType.BUY, 1, 1, quantity=Decimal("10"), price=Decimal("100"))]
    holding = HoldingInfo(
        ticker="AAPL", sector="Tech", classification_source=ClassificationSource.MANUAL,
        data_gaps=(DataGap.COST_BASIS, DataGap.CURRENCY),
    )
    service = PortfolioService(FakePortfolioProvider(summary, transactions, [holding]), usd_only_fx)

    analytics = await service.get_analytics(1)

    assert analytics is not None
    position = analytics.positions[0]
    assert position.classification_source == ClassificationSource.MANUAL
    assert set(position.data_gaps) == {DataGap.INDUSTRY, DataGap.COST_BASIS, DataGap.CURRENCY}
    assert analytics.unpriced_tickers == ("AAPL",)
    assert "PRICE" not in DataGap.__members__
