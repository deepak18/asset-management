"""Public foundation contracts, wholly fictitious data and no external providers."""

import pytest
from httpx import AsyncClient

from app.portfolio.accounts import SecurityCreate, SecurityInfo, ValuationCreate, ValuationView
from app.portfolio.schemas import AccountType, PortfolioCreate, PortfolioSummary


async def test_old_create_and_account_patch_contract(api_client: AsyncClient) -> None:
    old = await api_client.post(
        "/api/v1/portfolios", json={"name": "Fictitious", "base_currency": "USD"}
    )
    assert old.status_code == 201
    account = PortfolioSummary.model_validate(old.json())
    assert account.account_type == "UNKNOWN" and account.external_account_id is None
    new = PortfolioCreate(
        name="Retirement",
        base_currency="USD",
        account_type=AccountType.ROTH_401K,
        custodian="Fictitious",
        external_account_id="00001234",
    )
    created = await api_client.post("/api/v1/portfolios", json=new.model_dump(mode="json"))
    assert created.status_code == 201
    account = PortfolioSummary.model_validate(created.json())
    assert account.external_account_id == "00001234" and account.account_type == "ROTH_401K"
    path = f"/api/v1/portfolios/{account.id}"
    patched = await api_client.patch(path + "/account", json={"custodian": None})
    assert patched.status_code == 200
    assert patched.json()["external_account_id"] == "00001234"
    assert patched.json()["account_type"] == "ROTH_401K"
    assert patched.json()["custodian"] is None
    read = await api_client.get(path)
    assert read.status_code == 200 and read.json() == patched.json()
    for body in (
        {},
        {"account_type": None},
        {"external_account_id": 123},
        {"account_type": "401K"},
        {"unknown": True},
    ):
        assert (await api_client.patch(path + "/account", json=body)).status_code == 422
    assert (
        await api_client.patch("/api/v1/portfolios/999/account", json={"custodian": "Missing"})
    ).status_code == 404


async def test_securities_identity_and_scoped_alias_contract(api_client: AsyncClient) -> None:
    request = SecurityCreate.model_validate(
        {
            "name": "Fictitious 2050 Class A",
            "currency": "USD",
            "instrument_type": "TARGET_DATE_FUND",
            "aliases": [{"source_code": "TEST_A", "value": "0001"}],
        }
    )
    created = await api_client.post("/api/v1/securities", json=request.model_dump(mode="json"))
    assert created.status_code == 201
    first = SecurityInfo.model_validate(created.json())
    assert first.ticker is None and first.aliases[0].value == "0001"
    assert (
        await api_client.post("/api/v1/securities", json=request.model_dump(mode="json"))
    ).status_code == 409
    second = request.model_dump(mode="json") | {
        "name": "Fictitious 2050 Class B",
        "instrument_type": "COLLECTIVE_TRUST",
        "aliases": [{"source_code": "TEST_B", "value": "0001"}],
    }
    result = await api_client.post("/api/v1/securities", json=second)
    assert result.status_code == 201 and result.json()["id"] != first.id
    listed = await api_client.get("/api/v1/securities")
    assert listed.status_code == 200 and len(listed.json()) == 2
    for body in (
        {"name": " ", "currency": "USD"},
        {"name": "Fictitious", "currency": "US"},
        {"name": "Fictitious", "currency": "USD", "id": 1},
        {"name": "Fictitious", "currency": "USD", "instrument_type": "GUESS"},
    ):
        assert (await api_client.post("/api/v1/securities", json=body)).status_code == 422


async def test_valuations_separate_view_exact_repeat_conflict_latest_and_nulls(
    api_client: AsyncClient,
) -> None:
    path = "/api/v1/portfolios/1/valuations"
    empty = await api_client.get(path)
    assert empty.status_code == 200
    assert empty.json() == {
        "portfolio_id": 1,
        "view": "REPORTED_SNAPSHOT",
        "status": "EMPTY",
        "snapshot": None,
    }
    security = await api_client.post(
        "/api/v1/securities", json={"name": "Fictitious Trust", "currency": "USD"}
    )
    security_id = security.json()["id"]
    request = ValuationCreate.model_validate(
        {
            "as_of": "2026-01-31",
            "currency": "USD",
            "source_code": "TEST",
            "source_reference": "fiction.csv:7",
            "positions": [
                {
                    "security_id": security_id,
                    "quantity": "0.0123456789",
                    "reported_value": "100.0123456789",
                }
            ],
        }
    )
    before = (await api_client.get("/api/v1/portfolios/1/transactions")).json()
    old_analytics = (await api_client.get("/api/v1/portfolios/1/analytics")).json()
    created = await api_client.post(path, json=request.model_dump(mode="json"))
    assert created.status_code == 201
    view = ValuationView.model_validate(created.json())
    assert view.snapshot is not None
    assert created.json()["snapshot"]["reported_total"] == "100.0123456789"
    assert created.json()["snapshot"]["positions"][0]["quantity"] == "0.0123456789"
    assert view.snapshot.cost_basis is None and view.snapshot.unrealized_pnl is None
    assert (
        view.snapshot.money_weighted_return is None
        and view.snapshot.history_status == "VALUATION_ONLY"
    )
    assert view.snapshot.provenance.source_code == "TEST"
    assert view.snapshot.positions[0].provenance.source_reference == "fiction.csv:7"
    assert view.snapshot.provenance.imported_at.tzinfo is not None
    repeated = await api_client.post(path, json=request.model_dump(mode="json"))
    assert repeated.status_code == 201 and repeated.json() == created.json()
    assert (
        await api_client.post(
            path, json=request.model_dump(mode="json") | {"source_reference": "changed"}
        )
    ).status_code == 409
    older = await api_client.post(
        path,
        json=request.model_dump(mode="json")
        | {"as_of": "2026-01-01", "positions": [], "complete_snapshot": False},
    )
    assert older.status_code == 201 and older.json()["status"] == "PARTIAL"
    assert (await api_client.get(path)).json() == created.json()
    assert (await api_client.get("/api/v1/portfolios/1/transactions")).json() == before
    assert (await api_client.get("/api/v1/portfolios/1/analytics")).json() == old_analytics
    assert (await api_client.get("/api/v1/portfolios/999/valuations")).status_code == 404
    assert (
        await api_client.post(
            "/api/v1/portfolios/999/valuations", json=request.model_dump(mode="json")
        )
    ).status_code == 404


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "0.00000000001"])
@pytest.mark.parametrize("field", ["quantity", "reported_price", "reported_value", "cost_basis"])
async def test_invalid_valuation_amounts(api_client: AsyncClient, field: str, value: str) -> None:
    body = {
        "as_of": "2026-01-31",
        "currency": "USD",
        "positions": [{"security_id": 1, "quantity": "0", "reported_value": "0", field: value}],
    }
    assert (await api_client.post("/api/v1/portfolios/1/valuations", json=body)).status_code == 422


async def test_missing_security_currency_and_duplicate_position_validation(
    api_client: AsyncClient,
) -> None:
    body = {
        "as_of": "2026-01-31",
        "currency": "USD",
        "positions": [{"security_id": 999, "quantity": "0", "reported_value": "0"}],
    }
    assert (await api_client.post("/api/v1/portfolios/1/valuations", json=body)).status_code == 422
    assert (
        await api_client.post("/api/v1/portfolios/1/valuations", json=body | {"currency": "INR"})
    ).status_code == 422
    assert (
        await api_client.post(
            "/api/v1/portfolios/1/valuations", json=body | {"positions": body["positions"] * 2}
        )
    ).status_code == 422
    assert (
        await api_client.post(
            "/api/v1/portfolios/1/valuations", json={"currency": "USD", "positions": []}
        )
    ).status_code == 422
    assert (await api_client.get("/api/v1/portfolios/1/valuations")).json()["snapshot"] is None
