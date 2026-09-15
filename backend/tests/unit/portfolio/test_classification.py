"""Unit tests for the sector/industry classification backfill.

Both boundaries are faked: an in-memory holdings store standing in for the
portfolio provider/writer, and a canned market-data provider. No DB, no MCP, no
network — so what is under test is purely the service's policy decisions (what to
skip, what to overwrite, how failure degrades, how work is bounded).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.marketdata.errors import MarketDataUnavailableError
from app.marketdata.schemas import CompanyProfile, MarketDataProvenance
from app.portfolio.classification import HoldingClassificationService
from app.portfolio.schemas import HoldingInfo, PortfolioSummary

_PROVENANCE = MarketDataProvenance(
    provider_code="ALPHAVANTAGE",
    source_table="OVERVIEW",
    as_of=datetime(2026, 9, 1, tzinfo=UTC),
)


class _FakeHoldings:
    """Structural PortfolioProvider + PortfolioWriter over a dict."""

    def __init__(self, holdings: list[HoldingInfo], *, exists: bool = True) -> None:
        self.holdings = {h.ticker: h for h in holdings}
        self._exists = exists

    async def get_portfolio(self, portfolio_id: int) -> PortfolioSummary | None:
        if not self._exists:
            return None
        return PortfolioSummary(id=portfolio_id, name="Main", base_currency="USD")

    async def list_holdings(self, portfolio_id: int) -> list[HoldingInfo]:
        return [self.holdings[t] for t in sorted(self.holdings)]

    async def get_holding(self, portfolio_id: int, ticker: str) -> HoldingInfo | None:
        return self.holdings.get(ticker.upper())

    async def upsert_holding(
        self,
        portfolio_id: int,
        ticker: str,
        sector: str | None = None,
        industry: str | None = None,
    ) -> None:
        prev = self.holdings.get(ticker)
        self.holdings[ticker] = HoldingInfo(
            ticker=ticker,
            sector=sector if sector is not None else (prev.sector if prev else None),
            industry=(
                industry if industry is not None else (prev.industry if prev else None)
            ),
        )


class _FakeProfiles:
    """Canned company profiles; records which tickers were actually fetched."""

    def __init__(
        self,
        profiles: dict[str, CompanyProfile],
        *,
        failing: set[str] | None = None,
    ) -> None:
        self._profiles = profiles
        self._failing = failing or set()
        self.requested: list[str] = []

    async def get_company_profile(self, ticker: str) -> CompanyProfile | None:
        self.requested.append(ticker)
        if ticker in self._failing:
            raise MarketDataUnavailableError("quota exhausted")
        return self._profiles.get(ticker)


def _profile(ticker: str, sector: str | None, industry: str | None) -> CompanyProfile:
    return CompanyProfile(
        ticker=ticker,
        name=ticker,
        sector=sector,
        industry=industry,
        provenance=_PROVENANCE,
    )


def _service(holdings: _FakeHoldings, profiles: _FakeProfiles) -> HoldingClassificationService:
    return HoldingClassificationService(
        reader=holdings,  # type: ignore[arg-type]
        writer=holdings,  # type: ignore[arg-type]
        market_data=profiles,  # type: ignore[arg-type]
    )


async def test_missing_portfolio_returns_none() -> None:
    holdings = _FakeHoldings([], exists=False)
    result = await _service(holdings, _FakeProfiles({})).classify(999)
    assert result is None


async def test_unclassified_holding_is_backfilled() -> None:
    holdings = _FakeHoldings([HoldingInfo(ticker="NFLX")])
    profiles = _FakeProfiles({"NFLX": _profile("NFLX", "Communication Services", "Streaming")})

    result = await _service(holdings, profiles).classify(1)

    assert result is not None
    assert [h.ticker for h in result.classified] == ["NFLX"]
    assert result.classified[0].sector == "Communication Services"
    # The write actually landed, not just the response payload.
    assert holdings.holdings["NFLX"].industry == "Streaming"
    assert result.unresolved == ()
    assert result.remaining == 0


async def test_already_classified_holdings_are_skipped() -> None:
    """Hand-entered labels must survive a backfill, and cost no upstream quota."""

    holdings = _FakeHoldings([HoldingInfo(ticker="AAPL", sector="Mine")])
    profiles = _FakeProfiles({"AAPL": _profile("AAPL", "Vendor", "Hardware")})

    result = await _service(holdings, profiles).classify(1)

    assert result is not None
    assert result.skipped == ("AAPL",)
    assert result.classified == ()
    assert profiles.requested == []  # no call was made at all
    assert holdings.holdings["AAPL"].sector == "Mine"


async def test_refresh_overwrites_existing_classification() -> None:
    holdings = _FakeHoldings([HoldingInfo(ticker="AAPL", sector="Stale")])
    profiles = _FakeProfiles({"AAPL": _profile("AAPL", "Technology", "Hardware")})

    result = await _service(holdings, profiles).classify(1, refresh=True)

    assert result is not None
    assert result.skipped == ()
    assert holdings.holdings["AAPL"].sector == "Technology"


async def test_unknown_symbol_is_reported_unresolved() -> None:
    holdings = _FakeHoldings([HoldingInfo(ticker="ZZZZ")])
    result = await _service(holdings, _FakeProfiles({})).classify(1)

    assert result is not None
    assert result.unresolved == ("ZZZZ",)
    assert holdings.holdings["ZZZZ"].sector is None  # nothing invented


async def test_profile_without_taxonomy_is_unresolved_not_blank_write() -> None:
    holdings = _FakeHoldings([HoldingInfo(ticker="ABC")])
    profiles = _FakeProfiles({"ABC": _profile("ABC", None, None)})

    result = await _service(holdings, profiles).classify(1)

    assert result is not None
    assert result.unresolved == ("ABC",)
    assert result.classified == ()


async def test_upstream_failure_degrades_one_ticker_not_the_batch() -> None:
    """A rate-limited provider must not abort the tickers it could still answer."""

    holdings = _FakeHoldings([HoldingInfo(ticker="AAA"), HoldingInfo(ticker="BBB")])
    profiles = _FakeProfiles(
        {"BBB": _profile("BBB", "Energy", "Oil")}, failing={"AAA"}
    )

    result = await _service(holdings, profiles).classify(1)

    assert result is not None
    assert result.unresolved == ("AAA",)
    assert [h.ticker for h in result.classified] == ["BBB"]


async def test_limit_bounds_work_and_reports_remaining() -> None:
    """Quota and request time are both bounded; the caller is told to come back."""

    holdings = _FakeHoldings([HoldingInfo(ticker=t) for t in ("AAA", "BBB", "CCC")])
    profiles = _FakeProfiles(
        {t: _profile(t, "Sector", "Industry") for t in ("AAA", "BBB", "CCC")}
    )

    result = await _service(holdings, profiles).classify(1, limit=2)

    assert result is not None
    assert len(result.classified) == 2
    assert result.remaining == 1
    assert len(profiles.requested) == 2  # the third was never fetched


@pytest.mark.parametrize("limit", [1, 5])
async def test_repeated_calls_converge_to_zero_remaining(limit: int) -> None:
    holdings = _FakeHoldings([HoldingInfo(ticker=t) for t in ("AAA", "BBB", "CCC")])
    profiles = _FakeProfiles(
        {t: _profile(t, "Sector", "Industry") for t in ("AAA", "BBB", "CCC")}
    )
    service = _service(holdings, profiles)

    remaining = None
    for _ in range(5):
        result = await service.classify(1, limit=limit)
        assert result is not None
        remaining = result.remaining
        if remaining == 0:
            break

    assert remaining == 0
    assert all(h.sector == "Sector" for h in holdings.holdings.values())

