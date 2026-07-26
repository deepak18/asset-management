"""AlphaVantage market-data provider over MCP.

Implements :class:`~app.providers.marketdata_provider.MarketDataProvider` by calling
AlphaVantage tools on the hosted MCP server, mapping the JSON results into our typed
schemas, and serving everything through the read-through cache so the free-tier
network is the last resort. An optional throttle spaces out upstream calls.

Boundary discipline
--------------------
* The MCP client returns raw JSON *text*; we ``json.loads`` it and validate the
  pieces we need. Dynamic AlphaVantage keys (``"05. price"``, per-line-item
  statement fields) live only inside this mapping layer — never in the typed
  objects that leave it.
* AlphaVantage signals problems in-band: ``"Note"``/``"Information"`` mean
  rate-limit/quota (transient) → :class:`MarketDataUnavailableError`, which lets the
  cache fall back to a stale value; ``"Error Message"`` means bad symbol → treated
  as "no data" (returns ``None``, nothing cached).
* Every returned object carries :class:`MarketDataProvenance` (§7).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel

from app.marketdata.cache import ReadThroughCache
from app.marketdata.errors import MarketDataUnavailableError
from app.marketdata.schemas import (
    CompanyProfile,
    FinancialLineItem,
    FinancialStatement,
    FinancialStatements,
    MarketDataProvenance,
    MarketDataType,
    Quote,
)
from app.marketdata.throttle import AsyncRateLimiter
from app.mcp.client import McpClient
from app.mcp.errors import McpError

PROVIDER_CODE = "ALPHAVANTAGE"

# Tool names mirror AlphaVantage's REST function names. If the hosted server
# advertises different names, `McpClient.list_tools()` reveals them and only this
# mapping changes — no consumer is affected.
_QUOTE_TOOL = "GLOBAL_QUOTE"
_PROFILE_TOOL = "OVERVIEW"
_STATEMENT_TOOLS: dict[MarketDataType, str] = {
    MarketDataType.INCOME_STATEMENT: "INCOME_STATEMENT",
    MarketDataType.BALANCE_SHEET: "BALANCE_SHEET",
    MarketDataType.CASH_FLOW: "CASH_FLOW",
}

# Report-level metadata keys that are not financial line items.
_STATEMENT_META = {"fiscalDateEnding", "reportedCurrency"}
# Values AlphaVantage uses to mean "absent".
_ABSENT = {"None", "", "-", "—"}


class _NoDataError(Exception):
    """Internal: the source has no data for this symbol (→ provider returns None)."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AlphaVantageMarketDataProvider:
    """Cache-first market data from AlphaVantage over MCP."""

    def __init__(
        self,
        mcp: McpClient,
        cache: ReadThroughCache,
        *,
        throttle: AsyncRateLimiter | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._mcp = mcp
        self._cache = cache
        self._throttle = throttle
        self._now = now

    # -- MarketDataProvider -----------------------------------------------------

    async def get_quote(self, ticker: str) -> Quote | None:
        async def fetch() -> Quote:
            data = await self._fetch(_QUOTE_TOOL, {"symbol": ticker})
            return self._map_quote(ticker, data)

        return await self._cached(MarketDataType.QUOTE, ticker, Quote, fetch)

    async def get_company_profile(self, ticker: str) -> CompanyProfile | None:
        async def fetch() -> CompanyProfile:
            data = await self._fetch(_PROFILE_TOOL, {"symbol": ticker})
            return self._map_profile(ticker, data)

        return await self._cached(MarketDataType.PROFILE, ticker, CompanyProfile, fetch)

    async def get_financial_statements(
        self, ticker: str, statement_type: MarketDataType
    ) -> FinancialStatements | None:
        tool = _STATEMENT_TOOLS.get(statement_type)
        if tool is None:
            raise ValueError(f"{statement_type} is not a financial-statement type")

        async def fetch() -> FinancialStatements:
            data = await self._fetch(tool, {"symbol": ticker})
            return self._map_statements(ticker, statement_type, data)

        return await self._cached(statement_type, ticker, FinancialStatements, fetch)

    # -- cache + fetch plumbing -------------------------------------------------

    async def _cached[T: BaseModel](
        self,
        data_type: MarketDataType,
        ticker: str,
        schema: type[T],
        fetch: Callable[[], Any],
    ) -> T | None:
        try:
            outcome = await self._cache.get_or_fetch(
                data_type=data_type, symbol=ticker, schema=schema, fetch=fetch
            )
        except _NoDataError:
            return None
        return outcome.value

    async def _fetch(self, tool: str, arguments: dict[str, str]) -> Any:
        if self._throttle is not None:
            await self._throttle.acquire()
        try:
            text = await self._mcp.call_tool(tool, arguments)
        except McpError as exc:
            # Transport/tool failure → unavailable, so the cache can serve stale.
            raise MarketDataUnavailableError(f"AlphaVantage {tool} call failed: {exc}") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MarketDataUnavailableError(
                f"AlphaVantage {tool} returned non-JSON: {exc}"
            ) from exc
        self._check_envelope(data, tool)
        return data

    @staticmethod
    def _check_envelope(data: Any, tool: str) -> None:
        if not isinstance(data, dict):
            return
        if "Note" in data or "Information" in data:
            detail = data.get("Note") or data.get("Information")
            raise MarketDataUnavailableError(f"AlphaVantage rate limit on {tool}: {detail}")
        if "Error Message" in data:
            raise _NoDataError(str(data["Error Message"]))

    def _provenance(self, source_table: str) -> MarketDataProvenance:
        return MarketDataProvenance(
            provider_code=PROVIDER_CODE, source_table=source_table, as_of=self._now()
        )

    # -- mapping (dynamic AlphaVantage JSON → typed schemas) --------------------

    def _map_quote(self, ticker: str, data: Any) -> Quote:
        quote = data.get("Global Quote") if isinstance(data, dict) else None
        if not isinstance(quote, dict) or not quote:
            raise _NoDataError(f"no quote for {ticker}")
        price = _to_decimal(quote.get("05. price"))
        if price is None:
            raise _NoDataError(f"no price for {ticker}")
        return Quote(
            ticker=ticker,
            price=price,
            currency="USD",  # GLOBAL_QUOTE omits currency; US-listed = USD (PLAN §8)
            provenance=self._provenance(_QUOTE_TOOL),
        )

    def _map_profile(self, ticker: str, data: Any) -> CompanyProfile:
        if not isinstance(data, dict) or not data.get("Name"):
            raise _NoDataError(f"no profile for {ticker}")
        return CompanyProfile(
            ticker=ticker,
            name=str(data["Name"]),
            description=_opt_str(data.get("Description")),
            sector=_opt_str(data.get("Sector")),
            industry=_opt_str(data.get("Industry")),
            currency=_opt_str(data.get("Currency")),
            provenance=self._provenance(_PROFILE_TOOL),
        )

    def _map_statements(
        self, ticker: str, statement_type: MarketDataType, data: Any
    ) -> FinancialStatements:
        reports = data.get("annualReports") if isinstance(data, dict) else None
        if not isinstance(reports, list) or not reports:
            raise _NoDataError(f"no {statement_type} for {ticker}")
        source_table = _STATEMENT_TOOLS[statement_type]
        statements = tuple(
            self._map_report(ticker, statement_type, source_table, report)
            for report in reports
            if isinstance(report, dict)
        )
        return FinancialStatements(
            ticker=ticker, statement_type=statement_type, statements=statements
        )

    def _map_report(
        self,
        ticker: str,
        statement_type: MarketDataType,
        source_table: str,
        report: dict[str, Any],
    ) -> FinancialStatement:
        line_items = tuple(
            FinancialLineItem(tag=key, value=_to_decimal(value))
            for key, value in report.items()
            if key not in _STATEMENT_META
        )
        return FinancialStatement(
            ticker=ticker,
            statement_type=statement_type,
            fiscal_date_ending=_to_date(report.get("fiscalDateEnding")),
            currency=str(report.get("reportedCurrency") or "USD"),
            line_items=line_items,
            provenance=self._provenance(source_table),
        )


# -- small pure parsers ---------------------------------------------------------


def _to_decimal(raw: Any) -> Decimal | None:
    if raw is None or (isinstance(raw, str) and raw.strip() in _ABSENT):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _to_date(raw: Any) -> date:
    return date.fromisoformat(str(raw))


def _opt_str(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None



