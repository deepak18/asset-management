"""FX normalization seam (AGENTS.md §2 data-layer abstraction, §8 strong typing).

Design goals (PLAN.md decision #8 — "USD first, INR next"):

* Every cross-currency value in the portfolio math is routed through this helper,
  so enabling a new currency (INR) is **data/config only** — no calculator changes.
* Rates are **injected**, never fetched here. Fetching lives behind a
  ``MarketDataProvider`` later; this module is pure and deterministic.
* Conversion always uses the **transaction-date** rate (restatement-safe provenance).

All monetary math uses :class:`decimal.Decimal` to avoid binary float drift.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

# A rate is defined as: 1 unit of ``currency`` == ``rate_to_base`` units of the
# table's base currency, on ``as_of``. The base currency itself is always 1.


class Money(BaseModel):
    """A typed monetary amount tagged with its ISO currency code.

    Frozen (immutable) so a value, once created, can be safely passed around and
    used as a dict key / set member without risk of accidental mutation. The
    3-letter ``currency`` constraint mirrors ISO 4217 codes (USD, INR, ...).
    """

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)


class FxRate(BaseModel):
    """A single dated conversion rate into a base currency."""

    model_config = ConfigDict(frozen=True)

    currency: str = Field(min_length=3, max_length=3)
    as_of: date
    rate_to_base: Decimal = Field(gt=Decimal(0))


class MissingFxRateError(LookupError):
    """Raised when no injected rate can satisfy a requested conversion."""


class FxRateTable(BaseModel):
    """An injected, in-memory table of dated FX rates into ``base_currency``.

    Lookup rules:

    * Converting the base currency (or any amount already in the requested target)
      returns the amount unchanged — rate ``1``.
    * Otherwise the rate for ``(currency, on_date)`` must be present, else
      :class:`MissingFxRateError` is raised. We do **not** silently interpolate or
      fall back to a different date — provenance must be explicit.
    """

    base_currency: str = Field(min_length=3, max_length=3)
    rates: tuple[FxRate, ...] = ()

    def _rate_to_base(self, currency: str, on_date: date) -> Decimal:
        if currency == self.base_currency:
            return Decimal(1)
        for rate in self.rates:
            if rate.currency == currency and rate.as_of == on_date:
                return rate.rate_to_base
        raise MissingFxRateError(
            f"No FX rate for {currency}->{self.base_currency} on {on_date.isoformat()}"
        )

    def to_base(self, money: Money, on_date: date) -> Money:
        """Convert ``money`` into the table's base currency using the ``on_date`` rate."""

        rate = self._rate_to_base(money.currency, on_date)
        return Money(amount=money.amount * rate, currency=self.base_currency)

    def convert(self, money: Money, to_currency: str, on_date: date) -> Money:
        """Convert ``money`` into ``to_currency`` via the base currency on ``on_date``."""

        if money.currency == to_currency:
            return Money(amount=money.amount, currency=to_currency)
        in_base = self.to_base(money, on_date)
        if to_currency == self.base_currency:
            return in_base
        target_rate = self._rate_to_base(to_currency, on_date)
        return Money(amount=in_base.amount / target_rate, currency=to_currency)
