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
from app.portfolio.service import PortfolioService
from app.providers.base import PortfolioProvider
from app.providers.marketdata_provider import MarketDataProvider
from app.providers.portfolio_provider import SqlAlchemyPortfolioProvider


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
