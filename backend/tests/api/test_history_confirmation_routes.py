"""Review/repair/confirm HTTP contract over the real offline provider stack."""

import pytest
from httpx import AsyncClient

from app.main import create_app
from app.portfolio.schemas import HoldingHistoryReview

BASE = "/api/v1/portfolios/1"
HISTORY = f"{BASE}/holdings/AAPL/history"


async def test_review_is_active_scoped_ledger_with_decimal_strings(api_client: AsyncClient) -> None:
    response = await api_client.get(HISTORY.replace("AAPL", "aapl"))
    assert response.status_code == 200
    review = HoldingHistoryReview.model_validate(response.json())
    assert review.ticker == "AAPL" and review.history_complete
    assert review.confirmed_at is None and review.blocking_gaps == ()
    assert len(review.review_token) == 64
    assert response.json()["transactions"] == (await api_client.get(f"{BASE}/transactions")).json()
    assert isinstance(response.json()["transactions"][0]["price"], str)
    assert all(row.ticker == "AAPL" and row.portfolio_id == 1 for row in review.transactions)
    assert all(row.history_origin == "OBSERVED" for row in review.transactions)


async def test_explicit_confirmation_idempotent_and_changed_history_consistent(
    api_client: AsyncClient,
) -> None:
    initial = (await api_client.get(HISTORY)).json()
    body = {"review_token": initial["review_token"], "confirmed": True}
    response = await api_client.post(HISTORY, json=body)
    assert response.status_code == 200
    confirmed = response.json()
    assert confirmed["confirmed_at"] is not None and confirmed["history_complete"]
    assert (await api_client.post(HISTORY, json=body)).json() == confirmed
    assert (await api_client.get(HISTORY)).json() == confirmed
    # Missing transactions are repaired through the existing write contract.
    added = await api_client.post(f"{BASE}/transactions", json=[{
        "ticker": "aapl", "type": "BUY", "trade_date": "2024-01-01", "currency": "USD",
        "quantity": "2", "price": "90.00123",
    }])
    assert added.status_code == 201
    stale = (await api_client.get(HISTORY)).json()
    assert stale["confirmed_at"] is None and not stale["history_complete"]
    assert stale["history_gaps"] == ["HISTORY_CHANGED"] and stale["blocking_gaps"] == []
    assert len(stale["transactions"]) == 3
    assert (await api_client.post(HISTORY, json=body)).status_code == 409
    single = (await api_client.get(f"{BASE}/holdings/AAPL")).json()
    listed = next(row for row in (await api_client.get(f"{BASE}/holdings")).json() if row["ticker"] == "AAPL")
    position = next(row for row in (await api_client.get(f"{BASE}/analytics")).json()["positions"] if row["ticker"] == "AAPL")
    for result in (single, listed, position):
        assert not result["history_complete"] and result["history_gaps"] == ["HISTORY_CHANGED"]
    analytics = (await api_client.get(f"{BASE}/holdings/AAPL/analytics")).json()
    assert analytics["money_weighted_return"] is None
    assert analytics["money_weighted_return_status"] == "INCOMPLETE_HISTORY"
    fresh = await api_client.post(HISTORY, json={"review_token": stale["review_token"], "confirmed": True})
    assert fresh.status_code == 200 and fresh.json()["history_complete"]
    assert (await api_client.get(f"{BASE}/holdings/AAPL/analytics")).json()["money_weighted_return_status"] == "UNPRICED_POSITION"


async def test_deletion_stales_token_and_can_be_acknowledged_after_review(
    api_client: AsyncClient,
) -> None:
    initial = (await api_client.get(HISTORY)).json()
    body = {"review_token": initial["review_token"], "confirmed": True}
    assert (await api_client.post(HISTORY, json=body)).status_code == 200
    sale = initial["transactions"][1]["id"]
    assert (await api_client.delete(f"{BASE}/transactions/{sale}")).status_code == 204
    assert (await api_client.post(HISTORY, json=body)).status_code == 409
    review = (await api_client.get(HISTORY)).json()
    assert review["history_gaps"] == ["DELETED_TRANSACTION", "HISTORY_CHANGED"]
    assert len(review["transactions"]) == 1 and review["confirmed_at"] is None
    response = await api_client.post(HISTORY, json={"review_token": review["review_token"], "confirmed": True})
    assert response.status_code == 200 and response.json()["history_complete"]


@pytest.mark.parametrize("ack", [False, None, 0, 1, "true", "True", "1", [], {}])
async def test_acknowledgement_is_strict_boolean_true(api_client: AsyncClient, ack: object) -> None:
    token = (await api_client.get(HISTORY)).json()["review_token"]
    assert (await api_client.post(HISTORY, json={"review_token": token, "confirmed": ack})).status_code == 422
    assert (await api_client.get(HISTORY)).json()["confirmed_at"] is None


@pytest.mark.parametrize("body", [{}, {"review_token": "x"}, {"confirmed": True},
                                  {"review_token": 1, "confirmed": True}])
async def test_missing_or_invalid_required_fields(api_client: AsyncClient, body: object) -> None:
    assert (await api_client.post(HISTORY, json=body)).status_code == 422


@pytest.mark.parametrize("token", ["", "not-a-token", "0" * 64, "A" * 64])
async def test_malformed_or_stale_string_token_is_conflict(api_client: AsyncClient, token: str) -> None:
    response = await api_client.post(HISTORY, json={"review_token": token, "confirmed": True})
    assert response.status_code == 409


@pytest.mark.parametrize("path", ["/api/v1/portfolios/999/holdings/AAPL/history",
                                  f"{BASE}/holdings/MISSING/history"])
async def test_missing_identity_returns_404_for_both_methods(api_client: AsyncClient, path: str) -> None:
    assert (await api_client.get(path)).status_code == 404
    assert (await api_client.post(path, json={"review_token": "x", "confirmed": True})).status_code == 404


async def test_snapshot_and_empty_holding_are_not_acknowledgeable(api_client: AsyncClient) -> None:
    assert (await api_client.post(f"{BASE}/positions", json=[{
        "ticker": "SNAP", "quantity": "2", "currency": "USD", "as_of": "2024-01-01",
        "cost_basis_per_share": "100",
    }])).status_code == 201
    ledger = (await api_client.get(f"{BASE}/transactions")).json()
    snapshot = next(row for row in ledger if row["ticker"] == "SNAP")
    assert snapshot["history_origin"] == "SNAPSHOT" and snapshot["type"] == "BUY"
    for ticker, gap in (("SNAP", "SNAPSHOT"), ("XOM", "NO_TRANSACTIONS")):
        path = f"{BASE}/holdings/{ticker}/history"
        review = (await api_client.get(path)).json()
        if ticker == "SNAP":
            assert review["transactions"] == [snapshot]
        assert gap in review["blocking_gaps"]
        response = await api_client.post(path, json={"review_token": review["review_token"], "confirmed": True})
        assert response.status_code == 409
        assert (await api_client.get(path)).json() == review


@pytest.mark.parametrize("case", ["no_buy", "oversell", "future", "invalid_split"])
async def test_invalid_history_cannot_be_confirmed(api_client: AsyncClient, case: str) -> None:
    event = {"ticker": "BAD", "type": "BUY", "trade_date": "2024-01-01", "currency": "USD",
             "quantity": "1", "price": "100"}
    events = [event]
    if case == "no_buy":
        event.update(type="DIVIDEND", amount="10")
    elif case == "oversell":
        events.append({**event, "type": "SELL", "quantity": "2", "trade_date": "2024-02-01"})
    elif case == "future":
        event["trade_date"] = "9999-01-01"
    else:
        events.append({**event, "type": "SPLIT", "split_ratio": "0"})
    assert (await api_client.post(f"{BASE}/transactions", json=events)).status_code == 201
    path = f"{BASE}/holdings/BAD/history"
    review = (await api_client.get(path)).json()
    gap = "NO_ACQUISITION" if case == "no_buy" else "INVALID_LEDGER"
    assert gap in review["blocking_gaps"]
    assert (await api_client.post(path, json={"review_token": review["review_token"], "confirmed": True})).status_code == 409



def test_review_openapi_schema_and_statuses() -> None:
    schema = create_app().openapi()
    path = schema["paths"]["/api/v1/portfolios/{portfolio_id}/holdings/{ticker}/history"]
    assert {"200", "404", "422"} <= path["get"]["responses"].keys()
    assert {"200", "404", "409", "422"} <= path["post"]["responses"].keys()
    request = schema["components"]["schemas"]["HoldingHistoryConfirmation"]
    assert set(request["required"]) == {"review_token", "confirmed"}
    assert request["properties"]["confirmed"]["const"] is True
    assert request["properties"]["confirmed"]["type"] == "boolean"
    response = schema["components"]["schemas"]["HoldingHistoryReview"]
    assert set(response["required"]) == {"ticker", "history_complete", "history_gaps",
                                         "blocking_gaps", "review_token", "confirmed_at", "transactions"}
    assert {"type": "null"} in response["properties"]["confirmed_at"]["anyOf"]
    assert response["properties"]["transactions"]["type"] == "array"
    assert response["properties"]["transactions"]["items"]["$ref"].endswith("/TransactionRecord")
    record = schema["components"]["schemas"]["TransactionRecord"]
    assert "history_origin" in record["required"]
    assert record["properties"]["history_origin"] == {
        "$ref": "#/components/schemas/LedgerOrigin",
    }
    assert schema["components"]["schemas"]["LedgerOrigin"]["enum"] == [
        "OBSERVED", "SNAPSHOT", "UNKNOWN",
    ]
    write = schema["components"]["schemas"]["Transaction"]
    assert "history_origin" not in write["properties"]
    assert write["additionalProperties"] is False
