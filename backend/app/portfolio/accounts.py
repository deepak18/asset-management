"""Reported account snapshots: typed contracts, deterministic policy and orchestration.

This view never replays or augments the legacy ledger. Reported values are facts,
not quantity-times-price estimates; basis and dated cash flows may be unknown.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    model_validator,
)

from app.portfolio.schemas import AccountType, PortfolioSummary

if TYPE_CHECKING:
    # Type-only dependency avoids loading persistence infrastructure in pure policy tests.
    from app.providers.account_provider import AccountProvider

Currency = Annotated[str, StringConstraints(to_upper=True, pattern=r"^[A-Z]{3}$")]
SourceCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Reference = Annotated[str, StringConstraints(min_length=1, max_length=240)]
Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=28, decimal_places=10)]


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccountUpdate(Contract):
    """Omitted fields stay unchanged; null clears nullable strings, not account_type."""

    account_type: AccountType = AccountType.UNKNOWN
    custodian: str | None = Field(default=None, max_length=120)
    external_account_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def nonempty_patch(self) -> AccountUpdate:
        if not self.model_fields_set:
            raise ValueError("provide account metadata to update")
        return self


class InstrumentType(StrEnum):
    UNKNOWN = "UNKNOWN"
    STOCK = "STOCK"
    ETF = "ETF"
    MUTUAL_FUND = "MUTUAL_FUND"
    COLLECTIVE_TRUST = "COLLECTIVE_TRUST"
    TARGET_DATE_FUND = "TARGET_DATE_FUND"
    CASH = "CASH"
    OTHER = "OTHER"


class SecurityAlias(Contract):
    source_code: SourceCode
    value: Reference


class SecurityCreate(Contract):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    instrument_type: InstrumentType = InstrumentType.UNKNOWN
    ticker: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)] | None
    ) = None
    currency: Currency
    aliases: tuple[SecurityAlias, ...] = ()

    @model_validator(mode="after")
    def unique_aliases(self) -> SecurityCreate:
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError("duplicate source-scoped alias")
        return self


class SecurityInfo(SecurityCreate):
    id: int


class ValuationPositionInput(Contract):
    security_id: int = Field(gt=0, strict=True)
    quantity: Amount
    reported_price: Amount | None = None
    reported_value: Amount
    cost_basis: Amount | None = None
    source_reference: Reference | None = None

    @field_serializer("quantity", "reported_value")
    def required_decimal_string(self, value: Decimal) -> str:
        return canonical_decimal(value)

    @field_serializer("reported_price", "cost_basis")
    def optional_decimal_string(self, value: Decimal | None) -> str | None:
        return None if value is None else canonical_decimal(value)


def canonical_decimal(value: Decimal) -> str:
    """Context-free form: equivalent scales and negative zero hash alike."""
    if value == 0:
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


class ValuationCreate(Contract):
    as_of: date
    currency: Currency
    complete_snapshot: bool = Field(default=True, strict=True)
    positions: tuple[ValuationPositionInput, ...]
    source_code: SourceCode = "MANUAL"
    source_reference: Reference | None = None

    @model_validator(mode="after")
    def unique_securities(self) -> ValuationCreate:
        if len({position.security_id for position in self.positions}) != len(self.positions):
            raise ValueError("one position per security is required")
        return self


class StoredValuation(Contract):
    id: int
    portfolio_id: int
    data: ValuationCreate
    imported_at: datetime


class ValuationProvenance(Contract):
    source_code: str
    source_reference: str | None
    as_of: date
    imported_at: datetime


class ValuationPosition(ValuationPositionInput):
    unrealized_pnl: Decimal | None
    money_weighted_return: None = None
    history_status: Literal["VALUATION_ONLY"] = "VALUATION_ONLY"
    provenance: ValuationProvenance


class Availability(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"


class ValuationSnapshot(Contract):
    id: int
    portfolio_id: int
    as_of: date
    currency: Currency
    complete_snapshot: bool
    positions: tuple[ValuationPosition, ...]
    reported_total: Decimal
    cost_basis: Decimal | None
    unrealized_pnl: Decimal | None
    money_weighted_return: None = None
    history_status: Literal["VALUATION_ONLY"] = "VALUATION_ONLY"
    provenance: ValuationProvenance


class ValuationView(Contract):
    """Separate reported view, never an additive balance alongside the legacy ledger."""

    portfolio_id: int
    view: Literal["REPORTED_SNAPSHOT"] = "REPORTED_SNAPSHOT"
    status: Availability
    snapshot: ValuationSnapshot | None


class AccountNotFound(Exception):
    pass


class AccountValidationError(Exception):
    pass


class AccountConflict(Exception):
    pass


def canonical_snapshot_hash(data: ValuationCreate) -> str:
    """Hash all asserted content, independent of ordering/decimal spelling/import time."""
    ordered = data.model_copy(
        update={
            "positions": tuple(sorted(data.positions, key=lambda position: position.security_id)),
        }
    )
    return sha256(ordered.model_dump_json().encode("utf-8")).hexdigest()


def validate_snapshot_currency(
    data: ValuationCreate,
    base_currency: str,
    securities: tuple[SecurityInfo, ...],
) -> None:
    if data.currency != base_currency.upper():
        raise AccountValidationError(
            "snapshot currency must match portfolio base currency; FX unavailable"
        )
    if {p.security_id for p in data.positions} != {s.id for s in securities}:
        raise AccountValidationError("unknown security_id")
    if any(security.currency != data.currency for security in securities):
        raise AccountValidationError(
            "security currency must match snapshot currency; FX unavailable"
        )


def valuation_view(stored: StoredValuation) -> ValuationView:
    data = stored.data
    provenance = ValuationProvenance(
        source_code=data.source_code,
        source_reference=data.source_reference,
        as_of=data.as_of,
        imported_at=stored.imported_at,
    )
    # Inputs have at most 28 digits. Leave ample headroom for sums and differences.
    with localcontext() as context:
        context.prec = 60
        positions = tuple(
            ValuationPosition(
                security_id=p.security_id,
                quantity=p.quantity,
                reported_price=p.reported_price,
                reported_value=p.reported_value,
                cost_basis=p.cost_basis,
                source_reference=p.source_reference,
                unrealized_pnl=None if p.cost_basis is None else p.reported_value - p.cost_basis,
                provenance=provenance.model_copy(
                    update={
                        "source_reference": p.source_reference or data.source_reference,
                    }
                ),
            )
            for p in data.positions
        )
        total = sum((p.reported_value for p in positions), Decimal(0))
        basis = (
            sum((p.cost_basis for p in positions if p.cost_basis is not None), Decimal(0))
            if all(p.cost_basis is not None for p in positions)
            else None
        )
        pnl = None if basis is None else total - basis
    return ValuationView(
        portfolio_id=stored.portfolio_id,
        status=Availability.AVAILABLE if data.complete_snapshot else Availability.PARTIAL,
        snapshot=ValuationSnapshot(
            id=stored.id,
            portfolio_id=stored.portfolio_id,
            as_of=data.as_of,
            currency=data.currency,
            complete_snapshot=data.complete_snapshot,
            positions=positions,
            reported_total=total,
            cost_basis=basis,
            unrealized_pnl=pnl,
            provenance=provenance,
        ),
    )


class AccountService:
    def __init__(self, provider: AccountProvider) -> None:
        self._provider = provider

    async def update_account(self, portfolio_id: int, data: AccountUpdate) -> PortfolioSummary:
        return await self._provider.update_account(portfolio_id, data)

    async def create_security(self, data: SecurityCreate) -> SecurityInfo:
        return await self._provider.create_security(data)

    async def list_securities(self) -> tuple[SecurityInfo, ...]:
        return await self._provider.list_securities()

    async def write_valuation(self, portfolio_id: int, data: ValuationCreate) -> ValuationView:
        # Provider runs this pure validator under its transaction to avoid a read/write gap.
        stored = await self._provider.write_valuation(
            portfolio_id, data, canonical_snapshot_hash(data)
        )
        return valuation_view(stored)

    async def latest_valuation(self, portfolio_id: int) -> ValuationView:
        stored = await self._provider.latest_valuation(portfolio_id)
        if stored is None:
            return ValuationView(
                portfolio_id=portfolio_id, status=Availability.EMPTY, snapshot=None
            )
        return valuation_view(stored)
