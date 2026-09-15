"""Contract tests for the holding-classification routes.

These exercise the real app in-process (httpx ASGI transport) with the
market-data boundary swapped for a canned provider, so nothing here can reach
AlphaVantage or the network.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.api.conftest import SEEDED_PORTFOLIO_ID

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
    resp = await api_client_profiled.post(
        f"{_BASE}/holdings/classify?refresh=true&limit=1"
    )

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

