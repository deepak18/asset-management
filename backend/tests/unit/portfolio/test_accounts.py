"""Pure reported-valuation policy and mocked provider-boundary tests."""

from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.portfolio.accounts import (
    AccountService,
    AccountValidationError,
    Availability,
    SecurityInfo,
    StoredValuation,
    ValuationCreate,
    ValuationPositionInput,
    canonical_snapshot_hash,
    validate_snapshot_currency,
    valuation_view,
)
from app.providers.account_provider import AccountProvider


def position(
    security_id: int = 1, value: str = "123.4567890123", basis: str | None = None
) -> ValuationPositionInput:
    return ValuationPositionInput(
        security_id=security_id,
        quantity=Decimal("0.0000000001"),
        reported_value=Decimal(value),
        cost_basis=None if basis is None else Decimal(basis),
    )


def snapshot(*positions: ValuationPositionInput) -> ValuationCreate:
    return ValuationCreate(as_of=date(2026, 1, 31), currency="USD", positions=positions)


def test_hash_is_order_scale_and_context_independent() -> None:
    a = snapshot(position(), position(2, "0"))
    b = snapshot(position(2, "-0.00"), position(value="123.45678901230"))
    with localcontext() as context:
        context.prec = 3
        assert canonical_snapshot_hash(a) == canonical_snapshot_hash(b)
    for changed in (
        a.model_copy(update={"source_reference": "other"}),
        a.model_copy(update={"complete_snapshot": False}),
        a.model_copy(update={"as_of": date(2026, 2, 1)}),
        snapshot(position(basis="0"), position(2, "0")),
    ):
        assert canonical_snapshot_hash(a) != canonical_snapshot_hash(changed)


def test_null_unknown_basis_and_returns_and_exact_totals() -> None:
    stored = StoredValuation(
        id=1,
        portfolio_id=2,
        data=snapshot(position(), position(2, "0.0000000001", "0")),
        imported_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    with localcontext() as context:
        context.prec = 3
        view = valuation_view(stored)
    assert view.snapshot is not None
    assert view.snapshot.reported_total == Decimal("123.4567890124")
    assert view.snapshot.cost_basis is None
    assert view.snapshot.unrealized_pnl is None
    assert view.snapshot.money_weighted_return is None
    assert view.snapshot.positions[0].unrealized_pnl is None
    assert view.snapshot.positions[1].unrealized_pnl == Decimal("0.0000000001")
    assert view.snapshot.positions[0].provenance.source_code == "MANUAL"
    assert view.snapshot.positions[0].provenance.imported_at == stored.imported_at
    assert view.snapshot.positions[0].history_status == "VALUATION_ONLY"


def test_reported_value_is_authoritative_and_provenance_is_scoped() -> None:
    p = position(value="101", basis="100").model_copy(
        update={
            "reported_price": Decimal("999"),
            "source_reference": "line 7",
        }
    )
    data = snapshot(p).model_copy(
        update={"source_reference": "statement", "complete_snapshot": False}
    )
    result = valuation_view(
        StoredValuation(
            id=1,
            portfolio_id=1,
            data=data,
            imported_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
    )
    assert result.status == Availability.PARTIAL
    assert result.snapshot is not None
    assert result.snapshot.reported_total == Decimal("101")
    assert result.snapshot.unrealized_pnl == Decimal("1")
    assert result.snapshot.provenance.source_reference == "statement"
    assert result.snapshot.positions[0].provenance.source_reference == "line 7"


@pytest.mark.parametrize("field", ["quantity", "reported_price", "reported_value", "cost_basis"])
@pytest.mark.parametrize(
    "value", ["-1", "NaN", "Infinity", "-Infinity", "0.00000000001", "1000000000000000000"]
)
def test_invalid_decimal_is_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        ValuationPositionInput.model_validate(position().model_dump() | {field: value})


def test_duplicate_positions_rejected() -> None:
    with pytest.raises(ValidationError):
        snapshot(position(), position())


def test_currency_and_security_validation() -> None:
    data = snapshot(position())
    usd = SecurityInfo(id=1, name="Fictitious Class A", currency="USD")
    validate_snapshot_currency(data, "USD", (usd,))
    for base, securities in (
        ("INR", (usd,)),
        ("USD", ()),
        ("USD", (usd.model_copy(update={"currency": "INR"}),)),
    ):
        with pytest.raises(AccountValidationError):
            validate_snapshot_currency(data, base, securities)


async def test_service_passes_domain_hash_and_reads_empty_without_other_providers() -> None:
    provider = AsyncMock(spec=AccountProvider)
    data = snapshot(position())
    provider.write_valuation.return_value = StoredValuation(
        id=1,
        portfolio_id=4,
        data=data,
        imported_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    service = AccountService(provider)
    written = await service.write_valuation(4, data)
    assert written.snapshot is not None and written.snapshot.id == 1
    provider.write_valuation.assert_awaited_once_with(4, data, canonical_snapshot_hash(data))
    provider.latest_valuation.return_value = None
    empty = await service.latest_valuation(4)
    assert empty.status == Availability.EMPTY and empty.snapshot is None
