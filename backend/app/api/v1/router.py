"""v1 API router — aggregates every versioned route group under one include point.

Keeping a single aggregator means ``app.main`` mounts exactly one router, and new
domains (research, documents, marketdata, workspace) are added here as they land —
the app factory never changes.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import accounts, portfolio

api_router = APIRouter()
api_router.include_router(accounts.router)
api_router.include_router(portfolio.router)
