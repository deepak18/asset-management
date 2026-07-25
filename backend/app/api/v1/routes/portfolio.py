"""Portfolio HTTP routes — thin controllers only (no business logic).

Each handler does three things: declare its dependency, call it, and map absence to
a 404. All shaping/serialization is driven by the return-type annotation, which
FastAPI turns into the response model + OpenAPI schema the frontend generates from.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_portfolio_provider, get_portfolio_service
from app.portfolio.schemas import (
    HoldingInfo,
    PortfolioAnalytics,
    PortfolioSummary,
    Transaction,
)
from app.portfolio.service import PortfolioService
from app.providers.base import PortfolioProvider

router = APIRouter(prefix="/portfolios", tags=["Portfolio"])


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
