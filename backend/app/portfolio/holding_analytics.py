"""Holding-only returns, using typed I/O seams and the existing pure calculators."""

from datetime import date
from decimal import Decimal
from math import isfinite

from app.core.currency import FxRateTable, MissingFxRateError
from app.marketdata.errors import MarketDataUnavailableError
from app.portfolio.calculators import (
    XirrError,
    cost_basis_fifo,
    transactions_to_cash_flows,
    unrealized_pnl,
    xirr,
)
from app.portfolio.schemas import (
    CashFlow,
    HoldingAnalytics,
    HoldingReturnStatus,
    HoldingValuationSource,
    ImportStatus,
    LedgerOrigin,
    TransactionType,
)
from app.providers.base import HoldingAnalyticsProvider
from app.providers.marketdata_provider import MarketDataProvider


class HoldingAnalyticsService:
    def __init__(
        self,
        provider: HoldingAnalyticsProvider,
        fx: FxRateTable,
        market_data: MarketDataProvider | None = None,
    ) -> None:
        self._provider = provider
        self._fx = fx
        self._market_data = market_data

    async def get_analytics(
        self, portfolio_id: int, ticker: str, *, as_of: date | None = None
    ) -> HoldingAnalytics | None:
        """Return a scoped annualized fraction, or None for missing identity.

        ``as_of`` is injectable for deterministic tests; HTTP always values today.
        A last-known quote is marked at that date, not silently re-dated to its
        source timestamp. The original timestamp travels with the response.
        """
        today = as_of or date.today()
        portfolio = await self._provider.get_portfolio(portfolio_id)
        if portfolio is None:
            return None
        holding = await self._provider.get_holding(portfolio_id, ticker.upper())
        if holding is None:
            return None
        result = HoldingAnalytics(
            portfolio_id=portfolio_id,
            ticker=holding.ticker,
            base_currency=portfolio.base_currency,
            money_weighted_return_status=HoldingReturnStatus.INCOMPLETE_HISTORY,
            valuation_date=today,
        )
        ledger = await self._provider.get_holding_ledger(portfolio_id, holding.ticker)
        if (
            len(ledger.origins) != len(ledger.transactions)
            or any(origin != LedgerOrigin.OBSERVED for origin in ledger.origins)
            or ledger.has_unresolved_events
            or any(job.status != ImportStatus.SUCCEEDED or not job.history_complete
                   for job in ledger.imports)
        ):
            return result
        transactions = list(ledger.transactions)
        if any(
            txn.ticker.upper() != holding.ticker.upper() or txn.trade_date > today
            or any(not value.is_finite() or value < 0 for value in (
                txn.quantity, txn.price, txn.fees, txn.amount, txn.split_ratio,
            ))
            for txn in transactions
        ):
            return result.model_copy(update={
                "money_weighted_return_status": HoldingReturnStatus.INVALID_HISTORY,
            })
        # Never reinterpret injected rates relative to a different base currency.
        fx = self._fx if self._fx.base_currency == portfolio.base_currency else FxRateTable(
            base_currency=portfolio.base_currency
        )
        try:
            position = cost_basis_fifo(transactions, fx)
        except MissingFxRateError:
            return result.model_copy(update={
                "money_weighted_return_status": HoldingReturnStatus.MISSING_FX,
            })
        except ValueError:
            return result.model_copy(update={
                "money_weighted_return_status": HoldingReturnStatus.INVALID_HISTORY,
            })
        if transactions and not any(txn.type == TransactionType.BUY for txn in transactions):
            return result
        flows = transactions_to_cash_flows(transactions)
        if position.open_quantity > 0:
            result = result.model_copy(update={
                "money_weighted_return_status": HoldingReturnStatus.UNPRICED_POSITION,
            })
            if self._market_data is None:
                return result
            try:
                quote = await self._market_data.get_quote(holding.ticker)
            except MarketDataUnavailableError:
                return result
            if (
                quote is None or quote.ticker.upper() != holding.ticker.upper()
                or not quote.price.is_finite() or quote.price < 0
                or quote.provenance.as_of.date() > today
            ):
                return result
            result = result.model_copy(update={
                "valuation_source": HoldingValuationSource.QUOTE,
                "valuation_provenance": quote.provenance,
            })
            try:
                terminal = unrealized_pnl(position, quote.price, quote.currency, today, fx)
            except MissingFxRateError:
                return result.model_copy(update={
                    "money_weighted_return_status": HoldingReturnStatus.MISSING_FX,
                })
            flows.append(CashFlow(
                date=today, amount=terminal.market_value_base, currency=fx.base_currency,
            ))
        else:
            result = result.model_copy(update={
                "valuation_source": HoldingValuationSource.LEDGER,
                "valuation_date": max((txn.trade_date for txn in transactions), default=today),
            })
        try:
            rate = xirr(flows, fx)
            if not isfinite(rate):
                raise XirrError("Non-finite return")
        except MissingFxRateError:
            return result.model_copy(update={
                "money_weighted_return_status": HoldingReturnStatus.MISSING_FX,
            })
        except (XirrError, OverflowError, ZeroDivisionError):
            return result.model_copy(update={
                "money_weighted_return_status": HoldingReturnStatus.INSUFFICIENT_FLOWS,
            })
        return result.model_copy(update={
            "money_weighted_return": Decimal(str(rate)),
            "money_weighted_return_status": HoldingReturnStatus.OK,
        })
