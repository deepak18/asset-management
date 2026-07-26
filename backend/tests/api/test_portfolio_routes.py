"""Contract tests for the portfolio routes.

We assert on status codes, response *shape* (schema keys), and the computed values
that flow from provider -> service -> calculators. Decimal fields serialize to JSON
strings (Pydantic v2 default — it preserves exactness), so we compare via Decimal.
"""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient

from tests.api.conftest import SEEDED_PORTFOLIO_ID


async def test_health_ok(api_client: AsyncClient) -> None:
    resp = await api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_get_portfolio_returns_summary(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Main"
    assert body["base_currency"] == "USD"


async def test_get_portfolio_missing_returns_404(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/portfolios/999")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


async def test_list_transactions_shape_and_order(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/transactions")
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["type"] for r in rows] == ["BUY", "SELL"]
    assert Decimal(rows[0]["price"]) == Decimal("100")


async def test_list_holdings_maps_classification(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/holdings")
    assert resp.status_code == 200
    by_ticker = {h["ticker"]: h for h in resp.json()}
    assert by_ticker["AAPL"]["sector"] == "Tech"
    assert by_ticker["XOM"]["industry"] is None


async def test_analytics_computes_realized_and_open_cost(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/analytics")
    assert resp.status_code == 200
    body = resp.json()

    assert body["base_currency"] == "USD"
    # Bought 10@100, sold 4@150 -> realized 200; 6 shares open @100 = 600.
    assert Decimal(body["realized_pnl_base"]) == Decimal("200")
    assert Decimal(body["open_cost_basis_base"]) == Decimal("600")
    assert body["portfolio"]["name"] == "Main"
    assert len(body["positions"]) == 1
    # Two opposite-signed dated flows -> XIRR is defined (present, non-null).
    assert body["money_weighted_return"] is not None
    # No market-data provider in this client → market-value fields degrade cleanly.
    assert body["market_value_base"] is None
    assert body["positions_unrealized"] == []
    assert body["allocation_by_ticker"] == []


async def test_analytics_includes_market_values_when_priced(
    api_client_priced: AsyncClient,
) -> None:
    resp = await api_client_priced.get(f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/analytics")
    assert resp.status_code == 200
    body = resp.json()

    # 6 open AAPL shares @ current 150 = 900 market value; cost 600 → +300 unrealized.
    assert Decimal(body["market_value_base"]) == Decimal("900")
    assert Decimal(body["unrealized_pnl_base"]) == Decimal("300")
    assert len(body["positions_unrealized"]) == 1
    by_ticker = {r["key"]: r for r in body["allocation_by_ticker"]}
    assert Decimal(by_ticker["AAPL"]["weight"]) == Decimal("1")
    by_sector = {r["key"]: r for r in body["allocation_by_sector"]}
    assert Decimal(by_sector["Tech"]["market_value"]) == Decimal("900")
    assert body["unpriced_tickers"] == []
    assert body["priced_as_of"] is not None


async def test_analytics_missing_returns_404(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/portfolios/999/analytics")
    assert resp.status_code == 404
