"""Bounded multipart preview/confirmation and retained retirement source reads."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.api.deps import get_vanguard_service
from app.api.v1.routes.accounts import (
    AccountErrorResponse,
    AccountValidationResponse,
    account_errors,
)
from app.portfolio.accounts import AccountValidationError
from app.portfolio.vanguard import (
    ImportOptions,
    ObservedActivity,
    RetirementImport,
    RetirementPreview,
)
from app.portfolio.vanguard_service import (
    MAX_UPLOAD_BYTES,
    RetirementUploadTooLarge,
    VanguardService,
)

router = APIRouter(prefix="/portfolios/{portfolio_id}", tags=["retirement"])


@contextmanager
def retirement_errors() -> Iterator[None]:
    with account_errors():
        try:
            yield
        except RetirementUploadTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc


def import_options(
    as_of: Annotated[str, Form(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")],
    currency: Annotated[str, Form()],
    history_complete: Annotated[bool, Form()] = False,
) -> ImportOptions:
    with account_errors():
        try:
            return ImportOptions(
                as_of=date.fromisoformat(as_of),
                currency=currency,
                history_complete=history_complete,
            )
        except (ValueError, ValidationError) as exc:
            raise AccountValidationError("invalid ISO as_of date or currency") from exc


@router.post(
    "/retirement-imports/preview",
    response_model=RetirementPreview,
    responses={
        404: {"model": AccountErrorResponse},
        409: {"model": AccountErrorResponse},
        413: {"model": AccountErrorResponse},
        422: {"model": AccountValidationResponse},
    },
)
async def preview_import(
    portfolio_id: int,
    file: Annotated[UploadFile, File()],
    options: ImportOptions = Depends(import_options),
    service: VanguardService = Depends(get_vanguard_service),
) -> RetirementPreview:
    """Read-only review. Unknown codes remain visible and block confirmation."""
    with retirement_errors():
        return await service.preview(portfolio_id, await file.read(MAX_UPLOAD_BYTES + 1), options)


@router.post(
    "/retirement-imports",
    response_model=RetirementImport,
    status_code=201,
    responses={
        404: {"model": AccountErrorResponse},
        409: {"model": AccountErrorResponse},
        413: {"model": AccountErrorResponse},
        422: {"model": AccountValidationResponse},
    },
)
async def commit_import(
    portfolio_id: int,
    file: Annotated[UploadFile, File()],
    preview_token: Annotated[str, Form(min_length=1)],
    confirmed: Annotated[Literal["true"], Form()],
    options: ImportOptions = Depends(import_options),
    service: VanguardService = Depends(get_vanguard_service),
) -> RetirementImport:
    """Multipart confirmation is exactly the text `true`; no truthy coercions.

    Re-upload the reviewed bytes and options. State changes require a fresh preview.
    """
    with retirement_errors():
        return await service.commit(
            portfolio_id,
            await file.read(MAX_UPLOAD_BYTES + 1),
            options,
            preview_token,
        )


@router.get(
    "/retirement-imports",
    response_model=tuple[RetirementImport, ...],
    responses={404: {"model": AccountErrorResponse}},
)
async def import_history(
    portfolio_id: int,
    service: VanguardService = Depends(get_vanguard_service),
) -> tuple[RetirementImport, ...]:
    with account_errors():
        return await service.provider.history(portfolio_id)


@router.get(
    "/retirement-imports/{import_id}",
    response_model=RetirementImport,
    responses={404: {"model": AccountErrorResponse}},
)
async def import_detail(
    portfolio_id: int,
    import_id: int,
    service: VanguardService = Depends(get_vanguard_service),
) -> RetirementImport:
    with account_errors():
        return await service.provider.detail(portfolio_id, import_id)


@router.get(
    "/account-activity",
    response_model=tuple[ObservedActivity, ...],
    responses={404: {"model": AccountErrorResponse}},
)
async def account_activity(
    portfolio_id: int,
    service: VanguardService = Depends(get_vanguard_service),
) -> tuple[ObservedActivity, ...]:
    with account_errors():
        return await service.provider.activity(portfolio_id)
