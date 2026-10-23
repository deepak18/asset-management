"""In-process offline multipart retirement workflow and published schema contracts."""

import pytest
from httpx import AsyncClient

from app.main import create_app
from app.portfolio.vanguard_service import MAX_UPLOAD_BYTES
from tests.vanguard_fixtures import export

BASE = "/api/v1/portfolios/1"
FORM = {"as_of": "2026-01-31", "currency": "USD"}


async def test_preview_commit_reload_activity_and_separate_valuation_contract(
    api_client: AsyncClient,
) -> None:
    legacy = (await api_client.get(f"{BASE}/transactions")).json()
    content = export()
    response = await api_client.post(
        f"{BASE}/retirement-imports/preview", files={"file": ("fiction.csv", content)}, data=FORM
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["reported_total"] == "100.05" and preview["can_commit"] is True
    assert preview["funds"][0]["security_id"] is None and preview["funds"][0]["ticker"] is None
    assert preview["source"]["activity"][0]["account_number"] == "000042"
    assert preview["source"]["holdings"][0]["quantity"] == "10.0000000001"
    assert preview["cost_basis"] is None and preview["money_weighted_return"] is None
    assert preview["reconciliation"][0]["status"] == "HISTORY_INCOMPLETE"
    assert (await api_client.get(f"{BASE}/retirement-imports")).json() == []
    assert (await api_client.get("/api/v1/securities")).json() == []
    data = {**FORM, "preview_token": preview["preview_token"], "confirmed": "true"}
    response = await api_client.post(
        f"{BASE}/retirement-imports", files={"file": ("fiction.csv", content)}, data=data
    )
    assert response.status_code == 201, response.text
    committed = response.json()
    assert (
        committed["status"] == "COMMITTED"
        and committed["preview"]["funds"][0]["security_id"] is not None
    )
    assert (
        await api_client.get(f"{BASE}/retirement-imports/{committed['id']}")
    ).json() == committed
    assert (await api_client.get(f"{BASE}/retirement-imports")).json() == [committed]
    activity = (await api_client.get(f"{BASE}/account-activity")).json()
    assert len(activity) == 1 and activity[0]["import_id"] == committed["id"]
    assert activity[0]["fact"]["amount"] == "20.01" and activity[0]["source_code"] == "VANGUARD"
    assert activity[0]["fact"]["checksum"] in activity[0]["fact"]["source_reference"]
    snapshot = (await api_client.get(f"{BASE}/valuations")).json()["snapshot"]
    assert snapshot["reported_total"] == "100.05" and snapshot["cost_basis"] is None
    assert snapshot["as_of"] == "2026-01-31" and snapshot["money_weighted_return"] is None
    portfolio = (await api_client.get(BASE)).json()
    assert portfolio["external_account_id"] == "000042" and portfolio["custodian"] == "Vanguard"
    assert portfolio["account_type"] == "UNKNOWN"
    assert (await api_client.get(f"{BASE}/transactions")).json() == legacy
    duplicate = await api_client.post(
        f"{BASE}/retirement-imports", files={"file": ("fiction.csv", content)}, data=data
    )
    assert duplicate.status_code == 409 and "duplicate" in duplicate.text
    overlap = await api_client.post(
        f"{BASE}/retirement-imports/preview",
        files={"file": ("fiction.csv", export(units="12"))},
        data=FORM,
    )
    assert overlap.status_code == 409 and "nonoverlapping" in overlap.text


@pytest.mark.parametrize("confirmed", [None, "false", "True", "TRUE", "1", "yes", "null", ""])
async def test_confirmation_is_required_literal_true(
    api_client: AsyncClient, confirmed: str | None
) -> None:
    data = {**FORM, "preview_token": "token"}
    if confirmed is not None:
        data["confirmed"] = confirmed
    response = await api_client.post(
        f"{BASE}/retirement-imports", files={"file": ("fiction.csv", export())}, data=data
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "form",
    [
        {"currency": "USD"},
        {"as_of": "2026-01-31"},
        {"as_of": "01/31/2026", "currency": "USD"},
        {"as_of": "2026-02-30", "currency": "USD"},
        {"as_of": "2026-01-31T00:00:00", "currency": "USD"},
        {"as_of": "2026-01-31", "currency": "EUR"},
        {"as_of": "2026-01-31", "currency": "US"},
        {**FORM, "history_complete": "not-a-bool"},
    ],
)
async def test_invalid_options(api_client: AsyncClient, form: dict[str, str]) -> None:
    response = await api_client.post(
        f"{BASE}/retirement-imports/preview", files={"file": ("fiction.csv", export())}, data=form
    )
    assert response.status_code == 422


async def test_malformed_csv_upload_limit_missing_portfolios_and_imports(
    api_client: AsyncClient,
) -> None:
    for content, status in ((b"bad", 422), (b"x" * (MAX_UPLOAD_BYTES + 1), 413)):
        response = await api_client.post(
            f"{BASE}/retirement-imports/preview",
            files={"file": ("fiction.csv", content)},
            data=FORM,
        )
        assert response.status_code == status
    response = await api_client.post(
        f"{BASE}/retirement-imports",
        files={"file": ("fiction.csv", b"x" * (MAX_UPLOAD_BYTES + 1))},
        data={**FORM, "confirmed": "true", "preview_token": "token"},
    )
    assert response.status_code == 413
    for suffix in ("/retirement-imports", "/retirement-imports/1", "/account-activity"):
        assert (await api_client.get("/api/v1/portfolios/999" + suffix)).status_code == 404
    assert (await api_client.get(f"{BASE}/retirement-imports/999")).status_code == 404
    missing = await api_client.post(
        "/api/v1/portfolios/999/retirement-imports/preview",
        files={"file": ("fiction.csv", export())},
        data=FORM,
    )
    assert missing.status_code == 404


async def test_changed_options_bytes_and_account_state_reject_old_review(
    api_client: AsyncClient,
) -> None:
    preview = (
        await api_client.post(
            f"{BASE}/retirement-imports/preview",
            files={"file": ("fiction.csv", export())},
            data=FORM,
        )
    ).json()
    data = {**FORM, "preview_token": preview["preview_token"], "confirmed": "true"}
    for content, form in (
        (export(amount="20.02"), data),
        (export(), {**data, "as_of": "2026-02-01"}),
    ):
        response = await api_client.post(
            f"{BASE}/retirement-imports", files={"file": ("fiction.csv", content)}, data=form
        )
        assert response.status_code == 409 and "stale" in response.text
    assert (
        await api_client.patch(f"{BASE}/account", json={"custodian": "Changed"})
    ).status_code == 200
    response = await api_client.post(
        f"{BASE}/retirement-imports", files={"file": ("fiction.csv", export())}, data=data
    )
    assert response.status_code == 409 and "stale" in response.text
    await api_client.patch(f"{BASE}/account", json={"external_account_id": "00043"})
    response = await api_client.post(
        f"{BASE}/retirement-imports/preview", files={"file": ("fiction.csv", export())}, data=FORM
    )
    assert response.status_code == 409 and "bound" in response.text


async def test_unknown_closed_activity_and_complete_history_blockers_remain_visible(
    api_client: AsyncClient,
) -> None:
    content = export(
        extra_activity="42,01/01/2026,02/02/2026,9999,Closed transaction,Closed Fund,10,-2,20,\n"
    )
    preview = (
        await api_client.post(
            f"{BASE}/retirement-imports/preview",
            files={"file": ("fiction.csv", content)},
            data=FORM,
        )
    ).json()
    assert len(preview["source"]["activity"]) == 2 and len(preview["funds"]) == 2
    assert preview["can_commit"] is False
    closed = next(row for row in preview["reconciliation"] if row["fund_name"] == "Closed Fund")
    assert closed["net_supported_movement"] is None and closed["implied_prior_units"] is None
    assert any(issue["code"] == "UNSUPPORTED_ACTIVITY" for issue in preview["issues"])
    response = await api_client.post(
        f"{BASE}/retirement-imports",
        files={"file": ("fiction.csv", content)},
        data={**FORM, "preview_token": preview["preview_token"], "confirmed": "true"},
    )
    assert response.status_code == 409
    complete = (
        await api_client.post(
            f"{BASE}/retirement-imports/preview",
            files={"file": ("fiction.csv", export())},
            data={**FORM, "history_complete": "true"},
        )
    ).json()
    assert complete["can_commit"] is False
    assert any(i["code"] == "COMPLETE_HISTORY_MISMATCH" for i in complete["issues"])


def test_openapi_retirement_paths_statuses_and_decimal_null_contract() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]
    for suffix, method, success in (
        ("/retirement-imports/preview", "post", "200"),
        ("/retirement-imports", "post", "201"),
        ("/retirement-imports", "get", "200"),
        ("/retirement-imports/{import_id}", "get", "200"),
        ("/account-activity", "get", "200"),
    ):
        operation = paths["/api/v1/portfolios/{portfolio_id}" + suffix][method]
        assert success in operation["responses"] and "404" in operation["responses"]
        if method == "post":
            assert {"409", "413", "422"} <= operation["responses"].keys()
            assert "multipart/form-data" in operation["requestBody"]["content"]
    preview = schema["components"]["schemas"]["RetirementPreview"]["properties"]
    assert preview["reported_total"]["type"] == "string"
    assert preview["cost_basis"]["type"] == "null"
