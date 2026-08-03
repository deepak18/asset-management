"""Contract tests for the portfolio write endpoints (create / transactions /
positions / import).

Exercised against the real app in-process (see conftest). We assert status codes,
the ``LedgerIngestResult`` shape, that writes are visible to subsequent reads, and
that a position snapshot flows through to the analytics engine as an opening lot.
"""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient

from tests.api.conftest import SEEDED_PORTFOLIO_ID

_ROBINHOOD_CSV = (
    b"Activity Date,Process Date,Settle Date,Instrument,Description,"
    b"Trans Code,Quantity,Price,Amount\n"
    b"06/01/2022,06/01/2022,06/01/2022,NVDA,NVIDIA Corp,CDIV,,,$3.00\n"
    b"03/04/2021,03/05/2021,03/08/2021,NVDA,NVIDIA Corp,Sell,2,$200.00,$400.00\n"
    b"01/02/2020,01/03/2020,01/06/2020,NVDA,NVIDIA Corp,Buy,5,$100.00,($500.00)\n"
    b"06/02/2022,06/02/2022,06/02/2022,,ACH Deposit,ACH,,,$500.00\n"  # skipped + warning
)


async def test_list_portfolios_returns_seeded(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/portfolios")
    assert resp.status_code == 200
    rows = resp.json()
    assert any(p["id"] == SEEDED_PORTFOLIO_ID for p in rows)
    assert all({"id", "name", "base_currency"} <= p.keys() for p in rows)


async def test_created_portfolio_appears_in_list(api_client: AsyncClient) -> None:
    await api_client.post(
        "/api/v1/portfolios", json={"name": "Roth IRA", "base_currency": "USD"}
    )
    rows = (await api_client.get("/api/v1/portfolios")).json()
    assert "Roth IRA" in [p["name"] for p in rows]


async def test_create_portfolio_returns_201_and_identity(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/portfolios", json={"name": "Brokerage", "base_currency": "USD"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Brokerage"
    assert body["id"] > 0

    # The new portfolio is immediately readable.
    got = await api_client.get(f"/api/v1/portfolios/{body['id']}")
    assert got.status_code == 200


async def test_add_transactions_appends_to_ledger(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/transactions",
        json=[
            {
                "ticker": "TSLA", "type": "BUY", "trade_date": "2023-01-01",
                "currency": "USD", "quantity": "5", "price": "200",
            }
        ],
    )
    assert resp.status_code == 201
    assert resp.json()["created_transactions"] == 1
    assert resp.json()["tickers"] == ["TSLA"]

    rows = (await api_client.get(f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/transactions")).json()
    assert any(r["ticker"] == "TSLA" for r in rows)


async def test_add_position_snapshot_feeds_analytics(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/positions",
        json=[
            {
                "ticker": "GOOG", "quantity": "10", "currency": "USD",
                "as_of": "2020-01-01", "total_cost_basis": "1000",
                "sector": "Comm", "industry": "Internet",
            }
        ],
    )
    assert resp.status_code == 201
    assert resp.json()["created_transactions"] == 1

    analytics = (await api_client.get(f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/analytics")).json()
    goog = next(p for p in analytics["positions"] if p["ticker"] == "GOOG")
    # Snapshot recorded as one opening BUY lot: 10 shares @ 100 cost basis.
    assert Decimal(goog["open_quantity"]) == Decimal("10")
    assert Decimal(goog["open_cost_basis_base"]) == Decimal("1000")


async def test_snapshot_requires_exactly_one_cost_basis(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/positions",
        json=[{"ticker": "GOOG", "quantity": "10", "currency": "USD"}],  # neither form
    )
    assert resp.status_code == 422


async def test_import_accepts_and_processes_in_background(
    api_client: AsyncClient,
) -> None:
    """Upload returns 202 immediately; the job completes via the background task."""

    resp = await api_client.post(
        f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/imports",
        files={"file": ("robinhood.csv", _ROBINHOOD_CSV, "text/csv")},
    )
    assert resp.status_code == 202
    job = resp.json()
    assert job["status"] == "PENDING"
    assert job["source_format"] == "robinhood_csv"
    assert job["original_filename"] == "robinhood.csv"
    assert job["size_bytes"] == len(_ROBINHOOD_CSV)
    assert len(job["checksum"]) == 64  # sha-256 hex

    # httpx's ASGITransport runs background tasks before returning, so by now the
    # job is terminal and pollable through the status endpoint.
    status = (
        await api_client.get(
            f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/imports/{job['id']}"
        )
    ).json()
    assert status["status"] == "SUCCEEDED"
    assert status["created_transactions"] == 3  # buy, sell, dividend (ACH skipped)
    assert status["total_rows"] == 3
    assert status["processed_rows"] == 3
    assert status["tickers"] == ["NVDA"]
    assert any("cash transfer" in w.lower() for w in status["warnings"])
    assert status["error"] is None

    # The imported ledger flows straight into the deterministic analytics.
    analytics = (
        await api_client.get(f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/analytics")
    ).json()
    nvda = next(p for p in analytics["positions"] if p["ticker"] == "NVDA")
    # Bought 5@100 (=500), sold 2@200 -> realized 200; 3 shares open @100 = 300.
    assert Decimal(nvda["open_quantity"]) == Decimal("3")
    assert Decimal(nvda["open_cost_basis_base"]) == Decimal("300")
    assert Decimal(nvda["realized_pnl_base"]) == Decimal("200")
    assert Decimal(nvda["dividends_base"]) == Decimal("3")


async def test_reimporting_same_file_returns_409(api_client: AsyncClient) -> None:
    """Re-uploading identical bytes would double the ledger — it must be blocked."""

    url = f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/imports"
    files = {"file": ("robinhood.csv", _ROBINHOOD_CSV, "text/csv")}

    assert (await api_client.post(url, files=files)).status_code == 202
    second = await api_client.post(url, files=files)
    assert second.status_code == 409
    assert "already imported" in second.json()["detail"].lower()

    # Explicit override is still possible for a deliberate re-import.
    forced = await api_client.post(url + "?allow_duplicate=true", files=files)
    assert forced.status_code == 202


async def test_list_imports_returns_history(api_client: AsyncClient) -> None:
    await api_client.post(
        f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/imports",
        files={"file": ("robinhood.csv", _ROBINHOOD_CSV, "text/csv")},
    )
    rows = (
        await api_client.get(f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/imports")
    ).json()
    assert len(rows) == 1
    assert rows[0]["original_filename"] == "robinhood.csv"


async def test_import_status_404_for_unknown_job(api_client: AsyncClient) -> None:
    resp = await api_client.get(
        f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/imports/9999"
    )
    assert resp.status_code == 404


async def test_import_rejects_non_utf8_with_422(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/imports",
        files={"file": ("junk.csv", b"\xff\xfe\x00", "application/octet-stream")},
    )
    assert resp.status_code == 422


async def test_import_rejects_wrong_csv_shape_with_422(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        f"/api/v1/portfolios/{SEEDED_PORTFOLIO_ID}/imports",
        files={"file": ("other.csv", b"foo,bar\n1,2\n", "text/csv")},
    )
    assert resp.status_code == 422


async def test_import_to_missing_portfolio_returns_404(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/portfolios/999/imports",
        files={"file": ("robinhood.csv", _ROBINHOOD_CSV, "text/csv")},
    )
    assert resp.status_code == 404


async def test_write_to_missing_portfolio_returns_404(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/portfolios/999/transactions",
        json=[
            {
                "ticker": "TSLA", "type": "BUY", "trade_date": "2023-01-01",
                "currency": "USD", "quantity": "5", "price": "200",
            }
        ],
    )
    assert resp.status_code == 404

