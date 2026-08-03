"""FastAPI dependency wiring (the composition root for HTTP requests).

Each request gets its own DB session, and the provider/service are built on top of
it. Keeping this in one place means routes stay thin (they just declare *what* they
need via ``Depends`` and never construct infrastructure themselves), and tests can
override a single seam — ``get_session`` — to point at an in-memory SQLite engine.

The dependency chain mirrors the architecture boundary:
    get_session (AsyncSession)
        -> get_portfolio_provider (PortfolioProvider, I/O boundary)
            -> get_portfolio_service (PortfolioService, orchestration)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.currency import FxRateTable
from app.marketdata.alphavantage import PROVIDER_CODE, AlphaVantageMarketDataProvider
from app.marketdata.cache import ReadThroughCache
from app.mcp.client import StreamableHttpMcpClient
from app.mcp.registry import build_alphavantage_config
from app.portfolio.imports import StatementImportService
from app.portfolio.ingest import PortfolioIngestService
from app.portfolio.service import PortfolioService
from app.providers.base import PortfolioProvider, StatementImportStore
from app.providers.marketdata_provider import MarketDataProvider
from app.providers.portfolio_provider import SqlAlchemyPortfolioProvider
from app.providers.statement_import_store import SqlAlchemyStatementImportStore
from app.providers.statement_storage import StatementStorage
from app.storage.local_disk import LocalDiskStatementStorage


def get_settings_dep() -> Settings:
    """Expose cached settings as an overridable dependency."""

    return get_settings()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped async session from the app's session factory.

    The factory is created once at startup (see the lifespan in ``app.main``) and
    stashed on ``app.state``. ``async with`` guarantees the session is closed even
    if the handler raises. Tests override this dependency to inject their own engine.
    """

    factory = cast(
        "async_sessionmaker[AsyncSession]", request.app.state.session_factory
    )
    async with factory() as session:
        yield session


def get_portfolio_provider(
    session: AsyncSession = Depends(get_session),
) -> PortfolioProvider:
    """Build the SQLAlchemy provider for this request (returned as the interface)."""

    return SqlAlchemyPortfolioProvider(session)


def get_fx_table(settings: Settings = Depends(get_settings_dep)) -> FxRateTable:
    """Provide an FX table keyed to the configured base currency.

    Phase 1.1 ships an empty-rate table (USD-only works with no cross rates). When
    the market-data provider (§1.3) lands, injected rates flow in here unchanged.
    """

    return FxRateTable(base_currency=settings.base_currency)


def get_market_data_provider(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> MarketDataProvider | None:
    """Build the AlphaVantage-over-MCP provider, or ``None`` if not configured.

    Returns ``None`` when no MCP URL is set (``build_alphavantage_config`` disabled),
    so analytics degrades gracefully to cost-basis-only offline. No throttle is
    attached on the request path: the read-through cache is the free-tier guard, and
    a per-call delay would make a cold analytics request needlessly slow. (Batch/
    background refresh flows can attach an app-scoped ``AsyncRateLimiter`` later.)
    """

    config = build_alphavantage_config(settings)
    if config is None:
        return None
    cache = ReadThroughCache(
        session,
        ttl_seconds=settings.marketdata_cache_ttl_seconds,
        provider_code=PROVIDER_CODE,
    )
    return AlphaVantageMarketDataProvider(StreamableHttpMcpClient(config), cache)


def get_portfolio_service(
    provider: PortfolioProvider = Depends(get_portfolio_provider),
    fx: FxRateTable = Depends(get_fx_table),
    market_data: MarketDataProvider | None = Depends(get_market_data_provider),
) -> PortfolioService:
    """Compose the orchestration service from the provider + FX + market-data seams."""

    return PortfolioService(provider, fx, market_data=market_data)


def get_portfolio_ingest_service(
    session: AsyncSession = Depends(get_session),
) -> PortfolioIngestService:
    """Compose the write-side ingest service (manual entry, snapshots, import).

    One ``SqlAlchemyPortfolioProvider`` instance backs both the read (existence
    check) and write halves — the two Protocols exist to segregate capability at the
    call site, not to demand two objects over the same session.
    """

    provider = SqlAlchemyPortfolioProvider(session)
    return PortfolioIngestService(writer=provider, reader=provider)


def get_statement_storage(
    settings: Settings = Depends(get_settings_dep),
) -> StatementStorage:
    """Provide the blob store for raw uploaded statements (local disk by default).

    Returned as the interface so an S3-backed store can replace it by config alone.
    """

    return LocalDiskStatementStorage(settings.statement_storage_dir)


def get_statement_import_store(
    session: AsyncSession = Depends(get_session),
) -> StatementImportStore:
    """Provide read access to import-job status (returned as the interface)."""

    return SqlAlchemyStatementImportStore(session)


def get_statement_import_service(
    session: AsyncSession = Depends(get_session),
    storage: StatementStorage = Depends(get_statement_storage),
    settings: Settings = Depends(get_settings_dep),
) -> StatementImportService:
    """Compose the upload-acceptance service used by the request path."""

    provider = SqlAlchemyPortfolioProvider(session)
    return StatementImportService(
        store=SqlAlchemyStatementImportStore(session),
        storage=storage,
        reader=provider,
        writer=provider,
        batch_size=settings.import_batch_size,
        max_stored_warnings=settings.import_max_stored_warnings,
    )


class BackgroundImportRunner:
    """Runs a queued import **after** the HTTP response, on its own DB session.

    A request-scoped session is closed as soon as the response is sent, so the
    background job cannot borrow it — it would operate on a dead connection. This
    runner therefore holds the *session factory* and opens a fresh session per job,
    which is also what keeps the job's incremental progress commits visible to the
    separate requests that poll for status.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: StatementStorage,
        batch_size: int,
        max_stored_warnings: int,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._batch_size = batch_size
        self._max_stored_warnings = max_stored_warnings

    async def run(self, job_id: int, storage_key: str, portfolio_id: int) -> None:
        async with self._session_factory() as session:
            provider = SqlAlchemyPortfolioProvider(session)
            service = StatementImportService(
                store=SqlAlchemyStatementImportStore(session),
                storage=self._storage,
                reader=provider,
                writer=provider,
                batch_size=self._batch_size,
                max_stored_warnings=self._max_stored_warnings,
            )
            await service.process(job_id, storage_key, portfolio_id)


def get_background_import_runner(
    request: Request,
    storage: StatementStorage = Depends(get_statement_storage),
    settings: Settings = Depends(get_settings_dep),
) -> BackgroundImportRunner:
    """Build the background runner from the app-scoped session factory."""

    factory = cast(
        "async_sessionmaker[AsyncSession]", request.app.state.session_factory
    )
    return BackgroundImportRunner(
        factory,
        storage,
        batch_size=settings.import_batch_size,
        max_stored_warnings=settings.import_max_stored_warnings,
    )
