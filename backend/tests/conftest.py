"""Shared fixtures for the backend test suite.

Provider boundaries are mocked/faked here (there are none in the pure calculators
yet). We expose a couple of small FX tables so currency-normalization paths are
exercised without any network access.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.currency import FxRate, FxRateTable


@pytest.fixture
def usd_only_fx() -> FxRateTable:
    """A USD-base table with no cross rates — pure single-currency math."""

    return FxRateTable(base_currency="USD")


@pytest.fixture
def usd_inr_fx() -> FxRateTable:
    """USD-base table with a couple of dated INR rates for mixed-currency tests.

    1 INR == 0.012 USD on 2026-01-10; 1 INR == 0.011 USD on 2026-06-10.
    """

    return FxRateTable(
        base_currency="USD",
        rates=(
            FxRate(currency="INR", as_of=date(2026, 1, 10), rate_to_base=Decimal("0.012")),
            FxRate(currency="INR", as_of=date(2026, 6, 10), rate_to_base=Decimal("0.011")),
        ),
    )
