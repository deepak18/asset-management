"""Typed failures at the market-data boundary.

Kept small and intent-revealing so callers (and the read-through cache) can branch
on *why* a fetch failed rather than catching transport-specific exceptions.
"""

from __future__ import annotations


class MarketDataError(Exception):
    """Base class for market-data failures."""


class MarketDataUnavailableError(MarketDataError):
    """Upstream could not satisfy a fetch (rate-limited, network down, quota spent).

    The read-through cache catches this to decide whether it can serve a *stale*
    cached value as a graceful fallback (PLAN.md §1.3).
    """

