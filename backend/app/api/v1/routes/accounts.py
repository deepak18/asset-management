"""Account metadata, shared identities and the separate reported snapshot view."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, JsonValue

from app.api.deps import get_account_service
from app.portfolio.accounts import (
    AccountConflict,
    AccountNotFound,
    AccountService,
    AccountUpdate,
    AccountValidationError,
    SecurityCreate,
    SecurityInfo,
    ValuationCreate,
    ValuationView,
)
from app.portfolio.schemas import PortfolioSummary


class AccountErrorResponse(BaseModel):
    detail: str


class AccountValidationIssue(BaseModel):
    loc: tuple[str | int, ...]
    msg: str
    type: str
    input: JsonValue | None = None
    ctx: JsonValue | None = None


class AccountValidationResponse(BaseModel):
    detail: str | tuple[AccountValidationIssue, ...]


router = APIRouter(tags=["accounts"])


@contextmanager
def account_errors() -> Iterator[None]:
    try:
        yield
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/portfolios/{portfolio_id}/account",
    response_model=PortfolioSummary,
    responses={404: {"model": AccountErrorResponse}},
)
async def update_account(
    portfolio_id: int,
    data: AccountUpdate,
    service: AccountService = Depends(get_account_service),
) -> PortfolioSummary:
    with account_errors():
        return await service.update_account(portfolio_id, data)


@router.post(
    "/securities",
    response_model=SecurityInfo,
    status_code=201,
    responses={409: {"model": AccountErrorResponse}},
)
async def create_security(
    data: SecurityCreate,
    service: AccountService = Depends(get_account_service),
) -> SecurityInfo:
    """Create an immutable identity; only explicit source-scoped aliases deduplicate."""
    with account_errors():
        return await service.create_security(data)


@router.get("/securities", response_model=tuple[SecurityInfo, ...])
async def list_securities(
    service: AccountService = Depends(get_account_service),
) -> tuple[SecurityInfo, ...]:
    return await service.list_securities()


@router.post(
    "/portfolios/{portfolio_id}/valuations",
    response_model=ValuationView,
    status_code=201,
    responses={
        404: {"model": AccountErrorResponse},
        409: {"model": AccountErrorResponse},
        422: {"model": AccountValidationResponse},
    },
)
async def write_valuation(
    portfolio_id: int,
    data: ValuationCreate,
    service: AccountService = Depends(get_account_service),
) -> ValuationView:
    """Store a whole snapshot, not ledger events. Exact repeats also return 201.

    Unknown security IDs and currency mismatches return 422. A changed assertion
    for an existing portfolio/date returns 409; replacement is not supported.
    """
    with account_errors():
        return await service.write_valuation(portfolio_id, data)


@router.get(
    "/portfolios/{portfolio_id}/valuations",
    response_model=ValuationView,
    responses={404: {"model": AccountErrorResponse}},
)
async def latest_valuation(
    portfolio_id: int,
    service: AccountService = Depends(get_account_service),
) -> ValuationView:
    """Latest by as_of, never sum history or merge with the legacy ledger.

    Partial snapshots report only their own positions, not carried-forward values.
    Existing portfolios without a snapshot return EMPTY with snapshot=null.
    """
    with account_errors():
        return await service.latest_valuation(portfolio_id)
