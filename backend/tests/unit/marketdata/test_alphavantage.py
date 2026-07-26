"""AlphaVantage-over-MCP provider: mapping, cache-first, throttle, error handling.

The MCP client is a fake returning canned JSON — no network. The cache is real
(in-memory SQLite via ``async_session``), so we also prove the provider serves from
cache and falls back to stale data on upstream rate limits.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketdata.alphavantage import AlphaVantageMarketDataProvider
from app.marketdata.cache import ReadThroughCache
from app.marketdata.errors import MarketDataUnavailableError
from app.marketdata.schemas import MarketDataType
from app.mcp.errors import McpUnavailableError

_T0 = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)

_QUOTE_JSON = json.dumps(
    {"Global Quote": {"01. symbol": "AAPL", "05. price": "190.5500",
                      "07. latest trading day": "2026-07-24"}}
)
_OVERVIEW_JSON = json.dumps(
    {"Symbol": "AAPL", "Name": "Apple Inc", "Description": "Designs phones.",
     "Sector": "TECHNOLOGY", "Industry": "ELECTRONIC COMPUTERS", "Currency": "USD"}
)
_INCOME_JSON = json.dumps(
    {"symbol": "AAPL", "annualReports": [
        {"fiscalDateEnding": "2025-09-30", "reportedCurrency": "USD",
         "grossProfit": "180000000000", "researchAndDevelopment": "None"},
        {"fiscalDateEnding": "2024-09-30", "reportedCurrency": "USD",
         "grossProfit": "170000000000"},
    ]}
)
_RATE_LIMIT_JSON = json.dumps({"Note": "5 calls per minute limit reached."})
_ERROR_RATE_LIMIT_JSON = json.dumps(
    {"error": {"type": "rate_limit", "message": "25 requests per day reached."}}
)
_ERROR_OTHER_JSON = json.dumps(
    {"error": {"type": "invalid_symbol", "message": "Unknown symbol."}}
)
_BAD_SYMBOL_JSON = json.dumps({"Error Message": "Invalid API call."})


class _FakeMcp:
    """A stand-in ``McpClient`` returning canned text (or raising) per tool."""

    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def call_tool(self, tool: str, arguments: dict[str, str]) -> str:
        self.calls.append(tool)
        if tool not in self.responses:
            raise McpUnavailableError(f"no canned response for {tool}")
        return self.responses[tool]

    async def list_tools(self) -> tuple[str, ...]:
        return tuple(self.responses)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


class _ThrottleSpy:
    def __init__(self) -> None:
        self.count = 0

    async def acquire(self) -> None:
        self.count += 1


def _cache(session: AsyncSession, clock: _Clock, ttl: float = 3600) -> ReadThroughCache:
    return ReadThroughCache(session, ttl_seconds=ttl, provider_code="ALPHAVANTAGE", now=clock)


async def test_get_quote_maps_price_and_provenance(async_session: AsyncSession) -> None:
    fake = _FakeMcp({"GLOBAL_QUOTE": _QUOTE_JSON})
    provider = AlphaVantageMarketDataProvider(fake, _cache(async_session, _Clock(_T0)))

    quote = await provider.get_quote("AAPL")

    assert quote is not None
    assert quote.price == Decimal("190.55")
    assert quote.currency == "USD"
    assert quote.provenance.provider_code == "ALPHAVANTAGE"
    assert quote.provenance.source_table == "GLOBAL_QUOTE"
    assert fake.calls == ["GLOBAL_QUOTE"]


async def test_get_quote_is_cache_first(async_session: AsyncSession) -> None:
    fake = _FakeMcp({"GLOBAL_QUOTE": _QUOTE_JSON})
    provider = AlphaVantageMarketDataProvider(fake, _cache(async_session, _Clock(_T0)))

    await provider.get_quote("AAPL")
    await provider.get_quote("AAPL")  # served from cache

    assert fake.calls == ["GLOBAL_QUOTE"]  # upstream hit only once


async def test_throttle_runs_only_on_upstream_fetch(async_session: AsyncSession) -> None:
    fake = _FakeMcp({"GLOBAL_QUOTE": _QUOTE_JSON})
    throttle = _ThrottleSpy()
    provider = AlphaVantageMarketDataProvider(
        fake, _cache(async_session, _Clock(_T0)), throttle=throttle  # type: ignore[arg-type]
    )

    await provider.get_quote("AAPL")  # fetch → throttled
    await provider.get_quote("AAPL")  # cache hit → not throttled

    assert throttle.count == 1


async def test_invalid_symbol_returns_none(async_session: AsyncSession) -> None:
    fake = _FakeMcp({"GLOBAL_QUOTE": _BAD_SYMBOL_JSON})
    provider = AlphaVantageMarketDataProvider(fake, _cache(async_session, _Clock(_T0)))

    assert await provider.get_quote("NOPE") is None


async def test_rate_limit_without_cache_raises(async_session: AsyncSession) -> None:
    fake = _FakeMcp({"GLOBAL_QUOTE": _RATE_LIMIT_JSON})
    provider = AlphaVantageMarketDataProvider(fake, _cache(async_session, _Clock(_T0)))

    with pytest.raises(MarketDataUnavailableError):
        await provider.get_quote("AAPL")


async def test_error_envelope_rate_limit_raises(async_session: AsyncSession) -> None:
    # The hosted MCP server signals quota via {"error": {"type": "rate_limit"}}.
    fake = _FakeMcp({"GLOBAL_QUOTE": _ERROR_RATE_LIMIT_JSON})
    provider = AlphaVantageMarketDataProvider(fake, _cache(async_session, _Clock(_T0)))

    with pytest.raises(MarketDataUnavailableError):
        await provider.get_quote("AAPL")


async def test_error_envelope_non_rate_returns_none(async_session: AsyncSession) -> None:
    # A non-transient error (e.g. invalid symbol) is "no data", not unavailable.
    fake = _FakeMcp({"GLOBAL_QUOTE": _ERROR_OTHER_JSON})
    provider = AlphaVantageMarketDataProvider(fake, _cache(async_session, _Clock(_T0)))

    assert await provider.get_quote("NOPE") is None


async def test_rate_limit_falls_back_to_stale_cache(async_session: AsyncSession) -> None:
    fake = _FakeMcp({"GLOBAL_QUOTE": _QUOTE_JSON})
    clock = _Clock(_T0)
    provider = AlphaVantageMarketDataProvider(fake, _cache(async_session, clock, ttl=60))

    first = await provider.get_quote("AAPL")
    assert first is not None and first.price == Decimal("190.55")

    clock.advance(120)  # expire the cache entry
    fake.responses["GLOBAL_QUOTE"] = _ERROR_RATE_LIMIT_JSON  # now rate-limited

    stale = await provider.get_quote("AAPL")
    assert stale is not None
    assert stale.price == Decimal("190.55")  # last-known value, served despite quota


async def test_get_company_profile_maps_fields(async_session: AsyncSession) -> None:
    fake = _FakeMcp({"COMPANY_OVERVIEW": _OVERVIEW_JSON})
    provider = AlphaVantageMarketDataProvider(fake, _cache(async_session, _Clock(_T0)))

    profile = await provider.get_company_profile("AAPL")

    assert profile is not None
    assert profile.name == "Apple Inc"
    assert profile.sector == "TECHNOLOGY"
    assert profile.industry == "ELECTRONIC COMPUTERS"
    assert profile.provenance.source_table == "COMPANY_OVERVIEW"


async def test_get_financial_statements_maps_periods_and_missing(
    async_session: AsyncSession,
) -> None:
    fake = _FakeMcp({"INCOME_STATEMENT": _INCOME_JSON})
    provider = AlphaVantageMarketDataProvider(fake, _cache(async_session, _Clock(_T0)))

    statements = await provider.get_financial_statements(
        "AAPL", MarketDataType.INCOME_STATEMENT
    )

    assert statements is not None
    assert len(statements.statements) == 2
    first = statements.statements[0]
    assert first.fiscal_date_ending.isoformat() == "2025-09-30"
    assert first.currency == "USD"
    items = {li.tag: li.value for li in first.line_items}
    assert items["grossProfit"] == Decimal("180000000000")
    assert items["researchAndDevelopment"] is None  # "None" → absent, not 0
    assert "fiscalDateEnding" not in items  # metadata excluded from line items


async def test_unknown_statement_type_raises(async_session: AsyncSession) -> None:
    fake = _FakeMcp({})
    provider = AlphaVantageMarketDataProvider(fake, _cache(async_session, _Clock(_T0)))

    with pytest.raises(ValueError, match="financial-statement"):
        await provider.get_financial_statements("AAPL", MarketDataType.QUOTE)
