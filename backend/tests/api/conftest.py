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

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.portfolio.models  # noqa: F401  (registers ORM tables on Base.metadata)
from app.api.deps import get_session
from app.core.database import Base
from app.main import create_app
from app.portfolio import models
from app.portfolio.schemas import TransactionType

SEEDED_PORTFOLIO_ID = 1


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


@pytest_asyncio.fixture
async def api_client() -> AsyncIterator[AsyncClient]:
    """A ready-to-use async HTTP client bound to the app + a seeded in-memory DB."""

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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await engine.dispose()
