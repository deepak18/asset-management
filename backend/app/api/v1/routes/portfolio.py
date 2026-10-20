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
    get_holding_analytics_service,
    get_holding_classification_service,
    get_portfolio_ingest_service,
    get_portfolio_provider,
    get_portfolio_service,
    get_statement_import_service,
    get_statement_import_store,
)
from app.portfolio.classification import (
    DEFAULT_CLASSIFY_LIMIT,
    HoldingClassificationService,
)
from app.portfolio.holding_analytics import HoldingAnalyticsService
from app.portfolio.imports import (
    DuplicateStatementError,
    StatementImportService,
    storage_key_for,
)
from app.portfolio.ingest import PortfolioIngestService
from app.portfolio.schemas import (
    HoldingAnalytics,
    HoldingClassificationResult,
    HoldingClassificationUpdate,
    HoldingInfo,
    LedgerIngestResult,
    PortfolioAnalytics,
    PortfolioCreate,
    PortfolioSummary,
    PositionSnapshot,
    StatementFormat,
    StatementImportStatus,
    Transaction,
    UnresolvedItem,
    UnresolvedResolution,
)
from app.portfolio.service import PortfolioService
from app.portfolio.statements import StatementParseError
from app.providers.base import PortfolioProvider, StatementImportStore
from app.providers.statement_storage import StatementStorageError

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


@router.get("/{portfolio_id}/holdings/{ticker}", responses={404: {"description": "Holding absent"}})
async def get_holding(
    portfolio_id: int,
    ticker: str,
    provider: PortfolioProvider = Depends(get_portfolio_provider),
) -> HoldingInfo:
    """Return a single holding, including provenance and user-correctable gaps."""

    holding = await provider.get_holding(portfolio_id, ticker)
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    return holding


@router.get(
    "/{portfolio_id}/holdings/{ticker}/analytics",
    responses={404: {"description": "Portfolio or holding absent"}},
)
async def get_holding_analytics(
    portfolio_id: int,
    ticker: str,
    service: HoldingAnalyticsService = Depends(get_holding_analytics_service),
) -> HoldingAnalytics:
    """Ticker-only annualized XIRR, with explicit history/price/FX failure statuses.

    Open positions append a terminal valuation; closed positions need no quote.
    Unavailable returns are null. Snapshot or unconfirmed import history is refused.
    """
    analytics = await service.get_analytics(portfolio_id, ticker)
    if analytics is None:
        raise HTTPException(status_code=404, detail="Portfolio or holding not found")
    return analytics


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


@router.post(
    "/{portfolio_id}/holdings/classify",
    status_code=status.HTTP_200_OK,
    responses={503: {"description": "Market-data provider not configured"}},
)
async def classify_holdings(
    portfolio_id: int,
    refresh: bool = Query(False),
    limit: int = Query(DEFAULT_CLASSIFY_LIMIT, ge=1, le=200),
    after_ticker: str | None = Query(
        None,
        description="Pass next_cursor to advance past successful and unresolved tickers",
    ),
    service: HoldingClassificationService | None = Depends(get_holding_classification_service),
) -> HoldingClassificationResult:
    """Backfill sector/industry for this portfolio's holdings from company profiles.

    A broker statement carries no classification data, so imported holdings start
    unclassified and the allocation breakdown groups them under ``UNCLASSIFIED``.
    This fills them in from the market-data provider.

    MANUAL holdings (including manually cleared ones) and already-classified
    holdings are skipped unless ``refresh=true``. Process at most ``limit`` tickers.
    Continue with ``after_ticker=next_cursor`` until ``remaining=0``. Remaining
    strictly decreases along that cursor chain for an unchanged portfolio, even
    when lookups fail; repeating without a cursor has no such guarantee.
    Unresolved tickers are retried on a new sweep. Repeating a request is safe:
    it changes metadata only, never creates ledger events or duplicate holdings.

    Responds ``503`` when no market-data provider is configured — the remedy is an
    URL/key configuration, not a retry. Quota exhaustion or upstream outages
    instead return 200 with per-ticker ``PROVIDER_UNAVAILABLE`` failures (retry
    later). ``NO_PROFILE`` means no usable taxonomy was returned; manual entry
    remains available. No classification failure is treated as permanently final.
    """

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Market data is not configured; set ALPHAVANTAGE_API_KEY to enable "
                "sector/industry classification, or set them manually via "
                "PATCH /holdings/{ticker}"
            ),
        )

    result = await service.classify(
        portfolio_id, refresh=refresh, limit=limit, after_ticker=after_ticker
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio {portfolio_id} not found",
        )
    return result


@router.patch("/{portfolio_id}/holdings/{ticker}")
async def update_holding_classification(
    portfolio_id: int,
    ticker: str,
    body: HoldingClassificationUpdate,
    ingest: PortfolioIngestService = Depends(get_portfolio_ingest_service),
) -> HoldingInfo:
    """Manually set a holding's sector and/or industry (404 if it isn't held).

    The manual path intentionally does not depend on market data: classification
    must stay editable when the provider is unconfigured, rate-limited, or simply
    wrong about a symbol.

    Omission preserves a field; explicit null clears it. Always sets source MANUAL.
    Commits before returning: the next analytics GET uses the new grouping labels,
    with allocation weights computed on read when prices are available.
    """

    updated = await ingest.set_classification(portfolio_id, ticker, body)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Holding {ticker.upper()} not found in portfolio {portfolio_id}",
        )
    return updated


@router.post("/{portfolio_id}/imports", status_code=status.HTTP_202_ACCEPTED)
async def create_import(
    portfolio_id: int,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    source_format: StatementFormat = Query(StatementFormat.ROBINHOOD_CSV),
    allow_duplicate: bool = Query(False),
    history_complete: bool = Query(
        False,
        description="Confirm complete opening history to enable conservative split inference",
    ),
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

    data = await file.read(_MAX_UPLOAD_BYTES + 1)
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
            history_complete=history_complete,
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


@router.post(
    "/{portfolio_id}/imports/{job_id}/retry",
    status_code=202,
    responses={
        404: {"description": "Import absent"},
        409: {"description": "Not safely retryable"},
        422: {"description": "Stored bytes unavailable or corrupt"},
    },
)
async def retry_import(
    portfolio_id: int,
    job_id: int,
    background: BackgroundTasks,
    service: StatementImportService = Depends(get_statement_import_service),
    runner: BackgroundImportRunner = Depends(get_background_import_runner),
) -> StatementImportStatus:
    """Re-run a failed import from retained bytes; remove only its owned partial rows."""

    try:
        job = await service.retry(portfolio_id, job_id)
    except StatementStorageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    background.add_task(
        runner.run, job.id, storage_key_for(job.checksum, job.source_format), portfolio_id
    )
    return job


@router.get("/{portfolio_id}/unresolved")
async def list_unresolved(
    portfolio_id: int,
    include_resolved: bool = Query(False),
    store: StatementImportStore = Depends(get_statement_import_store),
) -> list[UnresolvedItem]:
    """List structured source items requiring user review across successful imports."""

    return await store.list_unresolved(portfolio_id, include_resolved)


@router.post(
    "/{portfolio_id}/unresolved/{item_id}/resolve",
    responses={
        404: {"description": "Item absent"},
        409: {"description": "Item already resolved"},
        422: {"description": "Invalid correction"},
    },
)
async def resolve_unresolved(
    portfolio_id: int,
    item_id: int,
    body: UnresolvedResolution,
    service: StatementImportService = Depends(get_statement_import_service),
    store: StatementImportStore = Depends(get_statement_import_store),
) -> UnresolvedItem:
    """Write a user correction and resolve its item atomically; duplicate resolution is rejected."""

    items = await store.list_unresolved(portfolio_id, include_resolved=True)
    if any(item.id == item_id and item.resolved for item in items):
        raise HTTPException(status_code=409, detail="Item already resolved")
    try:
        result = await service.resolve(portfolio_id, item_id, body)
    except ValueError as exc:
        code = 409 if str(exc) == "Item is already resolved" else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Unresolved item not found")
    return result


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
