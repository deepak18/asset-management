from httpx import AsyncClient

_BASE = "/api/v1/portfolios/1"
_CSV = (
    b"Activity Date,Instrument,Description,Trans Code,Quantity,Price,Amount\n"
    b"01/01/2020,NFLX,incoming,ITRF,3,,\n"
    b"01/02/2020,NFLX,split,SPL,3,,\n"
)


async def test_import_exposes_resolvable_items_and_clears_gaps(api_client: AsyncClient) -> None:
    client = api_client
    response = await client.post(f"{_BASE}/imports", files={"file": ("rh.csv", _CSV, "text/csv")})
    assert response.status_code == 202
    job_id = response.json()["id"]
    job = (await client.get(f"{_BASE}/imports/{job_id}")).json()
    assert job["status"] == "SUCCEEDED" and len(job["unresolved_items"]) == 2
    items = (await client.get(f"{_BASE}/unresolved")).json()
    assert items[0]["kind"] == "TRANSFER_IN_NO_COST_BASIS"
    assert items[0]["data_gaps"] == ["COST_BASIS"]
    detail = (await client.get(f"{_BASE}/holdings/NFLX")).json()
    assert set(detail["data_gaps"]) == {"SECTOR", "INDUSTRY", "COST_BASIS", "SPLIT_RATIO"}
    body = {
        "snapshot": {
            "ticker": "NFLX",
            "quantity": "3",
            "currency": "USD",
            "total_cost_basis": "300",
        }
    }
    url = f"{_BASE}/unresolved/{items[0]['id']}/resolve"
    assert (
        await client.post(url, json={"snapshot": {**body["snapshot"], "ticker": "TYPO"}})
    ).status_code == 422
    assert (await client.post(url, json=body)).status_code == 200
    assert (await client.post(url, json=body)).status_code == 409
    split = {
        "transaction": {
            "ticker": "NFLX",
            "type": "SPLIT",
            "currency": "USD",
            "trade_date": "2020-01-02",
            "split_ratio": "2",
        }
    }
    assert (
        await client.post(f"{_BASE}/unresolved/{items[1]['id']}/resolve", json=split)
    ).status_code == 200
    assert (await client.get(f"{_BASE}/unresolved")).json() == []
    detail = (await client.get(f"{_BASE}/holdings/NFLX")).json()
    assert set(detail["data_gaps"]) == {"SECTOR", "INDUSTRY"}
    analytics = (await client.get(f"{_BASE}/analytics")).json()
    netflix = next(pos for pos in analytics["positions"] if pos["ticker"] == "NFLX")
    assert netflix["open_quantity"] == "6"
    assert netflix["open_cost_basis_base"] == "300"
    assert (
        await client.post(f"/api/v1/portfolios/999/unresolved/{items[0]['id']}/resolve", json=body)
    ).status_code == 404


async def test_retry_absent_and_completed_jobs(api_client: AsyncClient) -> None:
    client = api_client
    assert (await client.post(f"{_BASE}/imports/999/retry")).status_code == 404
    response = await client.post(f"{_BASE}/imports", files={"file": ("rh.csv", _CSV)})
    assert response.status_code == 202
    assert (await client.post(f"{_BASE}/imports/{response.json()['id']}/retry")).status_code == 409


async def test_confirmed_history_is_explicit_opt_in(api_client: AsyncClient) -> None:
    data = (
        b"Activity Date,Instrument,Description,Trans Code,Quantity,Price,Amount\n"
        b"01/01/2020,MSFT,buy,Buy,1,$100,($100)\n"
        b"01/02/2020,MSFT,split,SPL,1,,\n"
    )
    response = await api_client.post(
        f"{_BASE}/imports?history_complete=true", files={"file": ("rh.csv", data)}
    )
    job_id = response.json()["id"]
    job = (await api_client.get(f"{_BASE}/imports/{job_id}")).json()
    assert job["history_complete"] is True
    assert job["created_transactions"] == 2
    assert job["unresolved_items"] == []
