"""Portfolio HTTP routes — thin controllers only (no business logic).

Each handler does three things: declare its dependency, call it, and map absence to
a 404. All shaping/serialization is driven by the return-type annotation, which
FastAPI turns into the response model + OpenAPI schema the frontend generates from.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.api.deps import (
    BackgroundImportRunner,
    get_background_import_runner,
    get_portfolio_ingest_service,
    get_portfolio_provider,
    get_portfolio_service,
    get_statement_import_service,
    get_statement_import_store,
)
from app.portfolio.imports import (
    DuplicateStatementError,
    StatementImportService,
    storage_key_for,
)
from app.portfolio.ingest import PortfolioIngestService
from app.portfolio.schemas import (
    HoldingInfo,
    LedgerIngestResult,
    PortfolioAnalytics,
    PortfolioCreate,
    PortfolioSummary,
    PositionSnapshot,
    StatementFormat,
    StatementImportStatus,
    Transaction,
)
from app.portfolio.service import PortfolioService
from app.portfolio.statements import StatementParseError
from app.providers.base import PortfolioProvider, StatementImportStore

router = APIRouter(prefix="/portfolios", tags=["Portfolio"])

# Reject oversized uploads before reading them fully into memory. Broker CSVs are
# tiny (a few hundred KB even for years of history); anything larger is almost
# certainly a mistake or abuse, so we cap it rather than risk unbounded allocation.
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.get("")
async def list_portfolios(
    provider: PortfolioProvider = Depends(get_portfolio_provider),
) -> list[PortfolioSummary]:
    """Return every tracked portfolio, for the UI's portfolio picker.

    Declared before ``/{portfolio_id}`` so FastAPI matches this literal path first.
    """

    return await provider.list_portfolios()


@router.get("/{portfolio_id}")
async def get_portfolio(
    portfolio_id: int,
    provider: PortfolioProvider = Depends(get_portfolio_provider),
) -> PortfolioSummary:
    """Return a portfolio's identity + base currency (404 if it doesn't exist)."""

    summary = await provider.get_portfolio(portfolio_id)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio {portfolio_id} not found",
        )
    return summary


@router.get("/{portfolio_id}/transactions")
async def list_transactions(
    portfolio_id: int,
    provider: PortfolioProvider = Depends(get_portfolio_provider),
) -> list[Transaction]:
    """Return the portfolio's full ledger as typed transactions."""

    return await provider.list_transactions(portfolio_id)


@router.get("/{portfolio_id}/holdings")
async def list_holdings(
    portfolio_id: int,
    provider: PortfolioProvider = Depends(get_portfolio_provider),
) -> list[HoldingInfo]:
    """Return the portfolio's tracked securities + classification metadata."""

    return await provider.list_holdings(portfolio_id)


@router.get("/{portfolio_id}/analytics")
async def get_analytics(
    portfolio_id: int,
    service: PortfolioService = Depends(get_portfolio_service),
) -> PortfolioAnalytics:
    """Return aggregated cost-basis / realized-P&L / XIRR analytics (404 if absent)."""

    analytics = await service.get_analytics(portfolio_id)
    if analytics is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio {portfolio_id} not found",
        )
    return analytics


# ---------------------------------------------------------------------------
# Write endpoints — create a portfolio, key in trades/snapshots, import a file
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    body: PortfolioCreate,
    ingest: PortfolioIngestService = Depends(get_portfolio_ingest_service),
) -> PortfolioSummary:
    """Create a new empty portfolio and return its assigned identity."""

    return await ingest.create_portfolio(body)


@router.post("/{portfolio_id}/transactions", status_code=status.HTTP_201_CREATED)
async def add_transactions(
    portfolio_id: int,
    body: list[Transaction],
    ingest: PortfolioIngestService = Depends(get_portfolio_ingest_service),
) -> LedgerIngestResult:
    """Append manually-entered ledger events (404 if the portfolio is absent)."""

    result = await ingest.add_transactions(portfolio_id, body)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio {portfolio_id} not found",
        )
    return result


@router.post("/{portfolio_id}/positions", status_code=status.HTTP_201_CREATED)
async def add_positions(
    portfolio_id: int,
    body: list[PositionSnapshot],
    ingest: PortfolioIngestService = Depends(get_portfolio_ingest_service),
) -> LedgerIngestResult:
    """Record current-holding snapshots as opening BUY lots (404 if absent).

    This is the fast on-ramp for an existing portfolio: assert each position's
    ticker, quantity, and cost basis instead of re-keying years of trades.
    """

    result = await ingest.add_snapshots(portfolio_id, body)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio {portfolio_id} not found",
        )
    return result


@router.post("/{portfolio_id}/imports", status_code=status.HTTP_202_ACCEPTED)
async def create_import(
    portfolio_id: int,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    source_format: StatementFormat = Query(StatementFormat.ROBINHOOD_CSV),
    allow_duplicate: bool = Query(False),
    service: StatementImportService = Depends(get_statement_import_service),
    runner: BackgroundImportRunner = Depends(get_background_import_runner),
) -> StatementImportStatus:
    """Accept a broker statement and process it in the background.

    Returns ``202 Accepted`` immediately with a ``PENDING`` job — a decade-long
    export can hold thousands of rows, far too slow to finish inside the request.
    Poll ``GET /portfolios/{id}/imports/{job_id}`` until the status is terminal,
    then refetch analytics.

    The upload's declared ``content_type`` is untrusted browser metadata, so the
    format comes from ``source_format`` and the parser validates the actual bytes.
    Re-uploading identical content is rejected with ``409`` (it would double-count
    the whole ledger); pass ``allow_duplicate=true`` to override deliberately.
    """

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Statement exceeds {_MAX_UPLOAD_BYTES} bytes",
        )

    try:
        job = await service.submit(
            portfolio_id,
            source_format,
            original_filename=file.filename or "statement",
            data=data,
            allow_duplicate=allow_duplicate,
        )
    except DuplicateStatementError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except StatementParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio {portfolio_id} not found",
        )

    # Queued to run after the response is sent, on its own DB session.
    background.add_task(
        runner.run,
        job.id,
        storage_key_for(job.checksum, source_format),
        portfolio_id,
    )
    return job


@router.get("/{portfolio_id}/imports")
async def list_imports(
    portfolio_id: int,
    store: StatementImportStore = Depends(get_statement_import_store),
) -> list[StatementImportStatus]:
    """Return the portfolio's import history, newest first."""

    return await store.list_jobs(portfolio_id)


@router.get("/{portfolio_id}/imports/{job_id}")
async def get_import(
    portfolio_id: int,
    job_id: int,
    store: StatementImportStore = Depends(get_statement_import_store),
) -> StatementImportStatus:
    """Return one import job's live status/progress (the endpoint the UI polls)."""

    job = await store.get_job(job_id)
    if job is None or job.portfolio_id != portfolio_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Import {job_id} not found for portfolio {portfolio_id}",
        )
    return job

