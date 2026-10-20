"""Contract tests for the holding-classification routes.

These exercise the real app in-process (httpx ASGI transport) with the
market-data boundary swapped for a canned provider, so nothing here can reach
AlphaVantage or the network.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.marketdata.errors import MarketDataUnavailableError
from tests.api.conftest import SEEDED_PORTFOLIO_ID, _FakeProfiledMarketData

_BASE = f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}"


async def test_classify_requires_market_data(api_client: AsyncClient) -> None:
    """Without a provider the answer is 503 + a fix, not a silent empty result."""

    resp = await api_client.post(f"{_BASE}/holdings/classify")

    assert resp.status_code == 503
    assert "ALPHAVANTAGE_API_KEY" in resp.json()["detail"]


async def test_classify_backfills_unclassified_holdings(
    api_client_profiled: AsyncClient,
) -> None:
    resp = await api_client_profiled.post(f"{_BASE}/holdings/classify")

    assert resp.status_code == 200
    body = resp.json()
    classified = {h["ticker"]: h for h in body["classified"]}
    assert classified["NFLX"]["sector"] == "Communication Services"
    assert classified["NFLX"]["industry"] == "Entertainment"
    # AAPL and XOM already carry a sector, so no quota was spent on them.
    assert sorted(body["skipped"]) == ["AAPL", "XOM"]
    assert body["remaining"] == 0

    # The write is durable: a follow-up read reflects it.
    holdings = (await api_client_profiled.get(f"{_BASE}/holdings")).json()
    by_ticker = {h["ticker"]: h for h in holdings}
    assert by_ticker["NFLX"]["sector"] == "Communication Services"


async def test_classify_reports_unresolved_symbols(
    api_client_profiled: AsyncClient,
) -> None:
    """refresh=true re-fetches everything; the fake only knows NFLX."""

    resp = await api_client_profiled.post(f"{_BASE}/holdings/classify?refresh=true")

    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body["unresolved"]) == ["AAPL", "XOM"]
    assert [h["ticker"] for h in body["classified"]] == ["NFLX"]


async def test_classify_limit_reports_remaining(api_client_profiled: AsyncClient) -> None:
    resp = await api_client_profiled.post(f"{_BASE}/holdings/classify?refresh=true&limit=1")

    assert resp.status_code == 200
    assert resp.json()["remaining"] == 2


async def test_classify_unknown_portfolio_is_404(api_client_profiled: AsyncClient) -> None:
    resp = await api_client_profiled.post("/api/v1/portfolios/999/holdings/classify")
    assert resp.status_code == 404


async def test_manual_classification_works_without_market_data(
    api_client: AsyncClient,
) -> None:
    """The manual path must stay usable when no provider is configured."""

    resp = await api_client.patch(
        f"{_BASE}/holdings/nflx", json={"sector": "Media", "industry": "Streaming"}
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "ticker": "NFLX",
        "sector": "Media",
        "industry": "Streaming",
        "classification_source": "MANUAL",
        "data_gaps": [],
    }


async def test_manual_classification_preserves_omitted_field(
    api_client: AsyncClient,
) -> None:
    resp = await api_client.patch(f"{_BASE}/holdings/AAPL", json={"industry": "Devices"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["industry"] == "Devices"
    assert body["sector"] == "Tech"  # untouched by a partial edit


async def test_manual_classification_rejects_empty_body(api_client: AsyncClient) -> None:
    resp = await api_client.patch(f"{_BASE}/holdings/AAPL", json={})
    assert resp.status_code == 422


async def test_manual_classification_unknown_ticker_is_404(
    api_client: AsyncClient,
) -> None:
    resp = await api_client.patch(f"{_BASE}/holdings/NOPE", json={"sector": "Tech"})
    assert resp.status_code == 404


async def test_detail_and_explicit_null_patch(api_client_profiled: AsyncClient) -> None:
    client = api_client_profiled
    cleared = await client.patch(f"{_BASE}/holdings/NFLX", json={"sector": None, "industry": None})
    assert cleared.status_code == 200
    assert cleared.json()["classification_source"] == "MANUAL"
    assert set(cleared.json()["data_gaps"]) == {"SECTOR", "INDUSTRY"}
    detail = await client.get(f"{_BASE}/holdings/nflx")
    assert detail.json() == cleared.json()
    assert (await client.get(f"{_BASE}/holdings/ABSENT")).status_code == 404
    assert (await client.get("/api/v1/portfolios/999/holdings/NFLX")).status_code == 404
    skipped = (await client.post(f"{_BASE}/holdings/classify")).json()
    assert "NFLX" in skipped["skipped"]
    refreshed = (await client.post(f"{_BASE}/holdings/classify?refresh=true")).json()
    assert refreshed["classified"][0]["classification_source"] == "PROVIDER"


async def test_patch_immediately_changes_analytics(api_client_priced: AsyncClient) -> None:
    response = await api_client_priced.patch(f"{_BASE}/holdings/AAPL", json={"sector": "Corrected"})
    assert response.status_code == 200
    analytics = (await api_client_priced.get(f"{_BASE}/analytics")).json()
    assert analytics["allocation_by_sector"][0]["key"] == "Corrected"
    assert analytics["positions"][0]["classification_source"] == "MANUAL"
    await api_client_priced.patch(f"{_BASE}/holdings/AAPL", json={"sector": None})
    analytics = (await api_client_priced.get(f"{_BASE}/analytics")).json()
    assert analytics["allocation_by_sector"][0]["key"] == "UNCLASSIFIED"
    assert analytics["positions"][0]["data_gaps"] == ["SECTOR"]


async def test_whitespace_is_not_a_classification(api_client: AsyncClient) -> None:
    response = await api_client.patch(f"{_BASE}/holdings/AAPL", json={"sector": "   "})
    assert response.status_code == 422


async def test_clear_one_field_preserves_the_other(api_client: AsyncClient) -> None:
    response = await api_client.patch(f"{_BASE}/holdings/AAPL", json={"sector": None})
    assert response.status_code == 200
    assert response.json() == {
        "ticker": "AAPL", "sector": None, "industry": "Hardware",
        "classification_source": "MANUAL", "data_gaps": ["SECTOR"],
    }
    invalid = await api_client.patch(
        f"{_BASE}/holdings/AAPL", json={"sector": "Tech", "industyr": "Typo"}
    )
    assert invalid.status_code == 422
    assert (await api_client.get(f"{_BASE}/holdings/AAPL")).json() == response.json()


async def test_cursor_sweep_terminates_and_repeat_never_adds_ledger_events(
    api_client_profiled: AsyncClient,
) -> None:
    client = api_client_profiled
    before = (await client.get(f"{_BASE}/transactions")).json()
    cursor = None
    seen = []
    for remaining in (2, 1, 0):
        params = {"refresh": "true", "limit": 1}
        if cursor is not None:
            params["after_ticker"] = cursor
        response = await client.post(f"{_BASE}/holdings/classify", params=params)
        assert response.status_code == 200
        body = response.json()
        assert body["remaining"] == remaining
        seen.extend(body["unresolved"] + [h["ticker"] for h in body["classified"]])
        cursor = body["next_cursor"]
    assert seen == ["AAPL", "NFLX", "XOM"] and cursor is None
    holdings = (await client.get(f"{_BASE}/holdings")).json()
    repeated = (await client.post(f"{_BASE}/holdings/classify")).json()
    assert repeated["classified"] == [] and repeated["remaining"] == 0
    assert (await client.get(f"{_BASE}/holdings")).json() == holdings
    assert (await client.get(f"{_BASE}/transactions")).json() == before


async def test_quota_exhaustion_is_retryable_not_configuration_503(
    api_client_profiled: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def quota_exhausted(self: object, ticker: str) -> None:
        raise MarketDataUnavailableError("quota exhausted")

    monkeypatch.setattr(_FakeProfiledMarketData, "get_company_profile", quota_exhausted)
    response = await api_client_profiled.post(f"{_BASE}/holdings/classify")
    assert response.status_code == 200
    body = response.json()
    assert body["unresolved"] == ["NFLX"] and body["remaining"] == 0
    assert body["failures"] == [{"ticker": "NFLX", "reason": "PROVIDER_UNAVAILABLE"}]
    assert (await api_client_profiled.get(f"{_BASE}/holdings/NFLX")).json()[
        "classification_source"
    ] == "NONE"
