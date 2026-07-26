"""Fixtures for API contract tests.

We exercise the *real* FastAPI app in-process via httpx ``ASGITransport`` — no
network socket, no uvicorn — which is the FastAPI-recommended way to test async
routes fast and deterministically.

The only seam we replace is the DB: ``get_session`` is overridden to hand out
sessions from a disposable in-memory SQLite engine (StaticPool keeps the single
in-memory connection alive across the test). Everything else — routing, dependency
wiring, serialization, the service, the provider — runs exactly as in production.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.marketdata.models  # noqa: F401  (registers the cache table on Base.metadata)
import app.portfolio.models  # noqa: F401  (registers ORM tables on Base.metadata)
from app.api.deps import get_market_data_provider, get_session
from app.core.database import Base
from app.main import create_app
from app.marketdata.schemas import MarketDataProvenance, Quote
from app.portfolio import models
from app.portfolio.schemas import TransactionType

SEEDED_PORTFOLIO_ID = 1


class _FakePricedMarketData:
    """A structural MarketDataProvider that prices AAPL at 150 (others: no data)."""

    async def get_quote(self, ticker: str) -> Quote | None:
        if ticker != "AAPL":
            return None
        return Quote(
            ticker="AAPL",
            price=Decimal("150"),
            currency="USD",
            provenance=MarketDataProvenance(
                provider_code="ALPHAVANTAGE",
                source_table="GLOBAL_QUOTE",
                as_of=datetime(2026, 7, 26, tzinfo=UTC),
            ),
        )

    async def get_company_profile(self, ticker: str) -> None:
        return None

    async def get_financial_statements(self, ticker: str, statement_type: object) -> None:
        return None


async def _seed(session: AsyncSession) -> None:
    """Insert one USD portfolio: AAPL bought 10@100 then sold 4@150; plus XOM meta."""

    portfolio = models.Portfolio(name="Main", base_currency="USD")
    session.add(portfolio)
    await session.flush()  # assigns portfolio.id

    session.add_all(
        [
            models.Holding(
                portfolio_id=portfolio.id, ticker="AAPL", sector="Tech", industry="Hardware"
            ),
            models.Holding(portfolio_id=portfolio.id, ticker="XOM", sector="Energy"),
            models.Transaction(
                portfolio_id=portfolio.id, ticker="AAPL", type=TransactionType.BUY,
                trade_date=date(2026, 1, 1), currency="USD",
                quantity=Decimal("10"), price=Decimal("100"),
            ),
            models.Transaction(
                portfolio_id=portfolio.id, ticker="AAPL", type=TransactionType.SELL,
                trade_date=date(2026, 3, 1), currency="USD",
                quantity=Decimal("4"), price=Decimal("150"),
            ),
        ]
    )
    await session.commit()


@asynccontextmanager
async def _build_client(
    market_data_override: Callable[[], object | None],
) -> AsyncIterator[AsyncClient]:
    """Build the real app over a seeded in-memory DB with a market-data override."""

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        await _seed(session)

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    # Never hit the live MCP server from tests — inject an explicit provider (or None).
    app.dependency_overrides[get_market_data_provider] = market_data_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await engine.dispose()


@pytest_asyncio.fixture
async def api_client() -> AsyncIterator[AsyncClient]:
    """App client with market data disabled (cost-basis analytics only, offline)."""

    async with _build_client(lambda: None) as client:
        yield client


@pytest_asyncio.fixture
async def api_client_priced() -> AsyncIterator[AsyncClient]:
    """App client whose market-data provider prices AAPL (for market-value asserts)."""

    async with _build_client(lambda: _FakePricedMarketData()) as client:
        yield client

