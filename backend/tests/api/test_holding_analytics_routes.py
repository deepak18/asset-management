from decimal import Decimal

import pytest
from httpx import AsyncClient


async def test_holding_return_is_independent_of_unrelated_unpriced_position(
    api_client_priced: AsyncClient,
) -> None:
    client = api_client_priced
    added = await client.post("/api/v1/portfolios/1/transactions", json=[{
        "ticker": "OTHER", "type": "BUY", "trade_date": "2020-01-01",
        "currency": "USD", "quantity": "1", "price": "20",
    }])
    assert added.status_code == 201
    portfolio = (await client.get("/api/v1/portfolios/1/analytics")).json()
    assert portfolio["money_weighted_return_status"] == "UNPRICED_POSITIONS"
    assert "OTHER" in portfolio["unpriced_tickers"]
    response = await client.get("/api/v1/portfolios/1/holdings/aapl/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["portfolio_id"] == 1
    assert body["base_currency"] == "USD"
    assert body["money_weighted_return_status"] == "OK"
    assert isinstance(body["money_weighted_return"], str)
    assert Decimal(body["money_weighted_return"]) > 0
    assert body["valuation_date"]
    assert body["valuation_source"] == "QUOTE"
    assert body["valuation_provenance"]["provider_code"] == "ALPHAVANTAGE"
    assert body["valuation_provenance"]["source_table"] == "GLOBAL_QUOTE"
    assert body["valuation_provenance"]["as_of"]


async def test_open_position_without_market_data(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/portfolios/1/holdings/AAPL/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["money_weighted_return"] is None
    assert body["money_weighted_return_status"] == "UNPRICED_POSITION"
    assert body["valuation_source"] == "UNAVAILABLE"
    assert body["valuation_provenance"] is None


async def test_closed_position_offline(api_client: AsyncClient) -> None:
    added = await api_client.post("/api/v1/portfolios/1/transactions", json=[{
        "ticker": "AAPL", "type": "SELL", "trade_date": "2026-04-01",
        "currency": "USD", "quantity": "6", "price": "150",
    }])
    assert added.status_code == 201
    response = await api_client.get("/api/v1/portfolios/1/holdings/AAPL/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["money_weighted_return_status"] == "OK"
    assert isinstance(body["money_weighted_return"], str)
    assert body["valuation_date"] == "2026-04-01"
    assert body["valuation_source"] == "LEDGER"
    assert body["valuation_provenance"] is None


async def test_snapshot_with_known_date_still_withholds_return(api_client_priced: AsyncClient) -> None:
    client = api_client_priced
    created = await client.post("/api/v1/portfolios", json={"name": "Snapshot", "base_currency": "USD"})
    pid = created.json()["id"]
    added = await client.post(f"/api/v1/portfolios/{pid}/positions", json=[{
        "ticker": "AAPL", "currency": "USD", "quantity": "10",
        "total_cost_basis": "1000", "as_of": "2020-01-01",
    }])
    assert added.status_code == 201
    response = await client.get(f"/api/v1/portfolios/{pid}/holdings/AAPL/analytics")
    assert response.status_code == 200
    assert response.json()["money_weighted_return"] is None
    assert response.json()["money_weighted_return_status"] == "INCOMPLETE_HISTORY"


@pytest.mark.parametrize("path", [
    "/api/v1/portfolios/999/holdings/AAPL/analytics",
    "/api/v1/portfolios/1/holdings/ABSENT/analytics",
])
async def test_missing_identity_is_404(api_client: AsyncClient, path: str) -> None:
    assert (await api_client.get(path)).status_code == 404


async def test_unrelated_missing_ledger_fx_does_not_block_ticker(api_client_priced: AsyncClient) -> None:
    client = api_client_priced
    response = await client.post("/api/v1/portfolios/1/transactions", json=[{
        "ticker": "EURO", "type": "BUY", "trade_date": "2020-01-01",
        "currency": "EUR", "quantity": "1", "price": "20",
    }])
    assert response.status_code == 201
    result = await client.get("/api/v1/portfolios/1/holdings/AAPL/analytics")
    assert result.status_code == 200
    assert result.json()["money_weighted_return_status"] == "OK"
    missing_fx = await client.get("/api/v1/portfolios/1/holdings/EURO/analytics")
    assert missing_fx.status_code == 200
    assert missing_fx.json()["money_weighted_return"] is None
    assert missing_fx.json()["money_weighted_return_status"] == "MISSING_FX"


@pytest.mark.parametrize("complete", [False, True])
async def test_import_requires_confirmed_complete_history(
    api_client_priced: AsyncClient, complete: bool,
) -> None:
    client = api_client_priced
    created = await client.post("/api/v1/portfolios", json={"name": "Import", "base_currency": "USD"})
    pid = created.json()["id"]
    uploaded = await client.post(
        f"/api/v1/portfolios/{pid}/imports?history_complete={str(complete).lower()}",
        files={"file": ("rh.csv", b"Activity Date,Instrument,Description,Trans Code,Quantity,Price,Amount\n"
                        b"01/01/2020,AAPL,buy,Buy,10,$100,($1000)\n", "text/csv")},
    )
    assert uploaded.status_code == 202
    job = await client.get(f"/api/v1/portfolios/{pid}/imports/{uploaded.json()['id']}")
    assert job.json()["status"] == "SUCCEEDED"
    response = await client.get(f"/api/v1/portfolios/{pid}/holdings/AAPL/analytics")
    assert response.status_code == 200
    if complete:
        assert response.json()["money_weighted_return_status"] == "OK"
        assert isinstance(response.json()["money_weighted_return"], str)
    else:
        assert response.json()["money_weighted_return_status"] == "INCOMPLETE_HISTORY"
        assert response.json()["money_weighted_return"] is None
