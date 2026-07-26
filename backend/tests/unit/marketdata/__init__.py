"""Unit tests for the market-data layer (schemas + read-through cache).

Fully offline (in-memory SQLite via the ``async_session`` fixture); the upstream
fetch is a fake so no network is touched (AGENTS.md §11 / PLAN.md §1.3).
"""

