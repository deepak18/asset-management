import pytest
from httpx import AsyncClient

BASE = "/api/v1/portfolios/1"


async def test_holding_table_history_flag_is_separate_from_prices_and_taxonomy(
    api_client: AsyncClient,
) -> None:
    client = api_client
    holdings = (await client.get(f"{BASE}/holdings")).json()
    by_ticker = {holding["ticker"]: holding for holding in holdings}
    assert by_ticker["AAPL"]["history_complete"] is True
    assert by_ticker["AAPL"]["history_gaps"] == []
    assert by_ticker["NFLX"]["history_complete"] is False
    assert by_ticker["NFLX"]["history_gaps"] == ["NO_TRANSACTIONS"]
    analytics = (await client.get(f"{BASE}/analytics")).json()
    assert analytics["positions"][0]["history_complete"] is True
    assert analytics["positions"][0]["history_gaps"] == []
    assert "AAPL" in analytics["unpriced_tickers"]
    # Changing labels cannot certify or invalidate transaction history.
    changed = await client.patch(f"{BASE}/holdings/AAPL", json={"sector": None})
    assert changed.json()["history_complete"] is True
    assert "SECTOR" in changed.json()["data_gaps"]


async def test_ledger_ids_are_stable_and_scoped(api_client: AsyncClient) -> None:
    first = (await api_client.get(f"{BASE}/transactions")).json()
    second = (await api_client.get(f"{BASE}/transactions")).json()
    assert first == second
    assert all(isinstance(row["id"], int) and row["portfolio_id"] == 1 for row in first)
    assert len({row["id"] for row in first}) == len(first)


async def test_delete_sale_commits_before_success_and_refreshes_analytics(api_client_priced: AsyncClient) -> None:
    client = api_client_priced
    before = (await client.get(f"{BASE}/transactions")).json()
    sale = next(row for row in before if row["type"] == "SELL")
    response = await client.delete(f"{BASE}/transactions/{sale['id']}")
    assert response.status_code == 204 and response.content == b""
    remaining = (await client.get(f"{BASE}/transactions")).json()
    assert len(remaining) == 1 and remaining[0]["type"] == "BUY"
    holding = (await client.get(f"{BASE}/holdings/aapl")).json()
    assert holding["history_complete"] is False
    assert holding["history_gaps"] == ["DELETED_TRANSACTION"]
    analytics = (await client.get(f"{BASE}/analytics")).json()
    assert analytics["positions"][0]["open_quantity"] == "10"
    assert analytics["positions"][0]["realized_pnl_base"] == "0"
    assert analytics["positions"][0]["history_complete"] is False
    assert analytics["positions"][0]["history_gaps"] == ["DELETED_TRANSACTION"]
    assert analytics["market_value_base"] == "1500"
    scoped = (await client.get(f"{BASE}/holdings/AAPL/analytics")).json()
    assert scoped["money_weighted_return"] is None
    assert scoped["money_weighted_return_status"] == "INCOMPLETE_HISTORY"
    assert (await client.delete(f"{BASE}/transactions/{sale['id']}")).status_code == 404


async def test_delete_purchase_with_dependent_sale_is_conflict(api_client: AsyncClient) -> None:
    before = (await api_client.get(f"{BASE}/transactions")).json()
    purchase = next(row for row in before if row["type"] == "BUY")
    response = await api_client.delete(f"{BASE}/transactions/{purchase['id']}")
    assert response.status_code == 409
    assert "without enough shares" in response.json()["detail"]
    assert (await api_client.get(f"{BASE}/transactions")).json() == before
    assert (await api_client.get(f"{BASE}/holdings/AAPL")).json()["history_complete"] is True


async def test_wrong_portfolio_and_missing_ids_are_404(api_client: AsyncClient) -> None:
    row = (await api_client.get(f"{BASE}/transactions")).json()[0]
    created = await api_client.post("/api/v1/portfolios", json={"name": "Other", "base_currency": "USD"})
    pid = created.json()["id"]
    for path in (
        f"/api/v1/portfolios/{pid}/transactions/{row['id']}",
        f"/api/v1/portfolios/999/transactions/{row['id']}",
        f"{BASE}/transactions/99999",
    ):
        assert (await api_client.delete(path)).status_code == 404
    assert len((await api_client.get(f"{BASE}/transactions")).json()) == 2


@pytest.mark.parametrize("extra", [
    {"id": 999}, {"portfolio_id": 2}, {"deleted_at": "2024-01-01"},
    {"history_origin": "OBSERVED"}, {"history_origin": "SNAPSHOT"},
    {"history_origin": "UNKNOWN"},
])
async def test_write_inputs_cannot_supply_read_identity(api_client: AsyncClient, extra: dict[str, object]) -> None:
    response = await api_client.post(f"{BASE}/transactions", json=[{
        "ticker": "AAA", "type": "BUY", "trade_date": "2024-01-01", "currency": "USD",
        "quantity": "1", "price": "100", **extra,
    }])
    assert response.status_code == 422
    assert len((await api_client.get(f"{BASE}/transactions")).json()) == 2


@pytest.mark.parametrize("complete", [False, True])
async def test_import_confirmation_flag_is_exposed_on_holdings(
    api_client: AsyncClient, complete: bool,
) -> None:
    created = await api_client.post("/api/v1/portfolios", json={"name": "Import", "base_currency": "USD"})
    pid = created.json()["id"]
    uploaded = await api_client.post(
        f"/api/v1/portfolios/{pid}/imports?history_complete={str(complete).lower()}",
        files={"file": ("rh.csv", b"Activity Date,Instrument,Description,Trans Code,Quantity,Price,Amount\n"
                        b"01/01/2024,AAA,buy,Buy,10,$100,($1000)\n", "text/csv")},
    )
    assert uploaded.status_code == 202
    holdings = (await api_client.get(f"/api/v1/portfolios/{pid}/holdings")).json()
    assert holdings[0]["history_complete"] == complete
    assert holdings[0]["history_gaps"] == ([] if complete else ["IMPORT_NOT_COMPLETE"])
    record = (await api_client.get(f"/api/v1/portfolios/{pid}/transactions")).json()[0]
    assert (await api_client.delete(f"/api/v1/portfolios/{pid}/transactions/{record['id']}")).status_code == 204
    job = (await api_client.get(f"/api/v1/portfolios/{pid}/imports/{uploaded.json()['id']}")).json()
    assert job["retry_safe"] is False
    assert job["history_complete"] == complete  # Original source attestation is not rewritten.
