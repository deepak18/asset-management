"""Tests for allocation weight calculation (app.portfolio.calculators.allocation_weights)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.portfolio.calculators import allocation_weights
from app.portfolio.schemas import PositionValue


def test_empty_ledger_returns_empty_list() -> None:
    assert allocation_weights([]) == []


def test_single_position_is_full_weight() -> None:
    rows = allocation_weights([PositionValue(ticker="AAPL", market_value=Decimal("1000"))])
    assert len(rows) == 1
    assert rows[0].key == "AAPL"
    assert rows[0].weight == Decimal("1")


def test_weights_sum_to_one_by_ticker() -> None:
    positions = [
        PositionValue(ticker="AAPL", market_value=Decimal("600")),
        PositionValue(ticker="MSFT", market_value=Decimal("300")),
        PositionValue(ticker="NVDA", market_value=Decimal("100")),
    ]
    rows = allocation_weights(positions)
    assert sum(r.weight for r in rows) == Decimal("1")
    weights = {r.key: r.weight for r in rows}
    assert weights["AAPL"] == Decimal("0.6")
    assert weights["MSFT"] == Decimal("0.3")
    assert weights["NVDA"] == Decimal("0.1")


def test_sorted_descending_by_value() -> None:
    positions = [
        PositionValue(ticker="A", market_value=Decimal("100")),
        PositionValue(ticker="B", market_value=Decimal("300")),
        PositionValue(ticker="C", market_value=Decimal("200")),
    ]
    rows = allocation_weights(positions)
    assert [r.key for r in rows] == ["B", "C", "A"]


def test_group_by_sector_aggregates() -> None:
    positions = [
        PositionValue(ticker="AAPL", market_value=Decimal("400"), sector="Tech"),
        PositionValue(ticker="MSFT", market_value=Decimal("400"), sector="Tech"),
        PositionValue(ticker="XOM", market_value=Decimal("200"), sector="Energy"),
    ]
    rows = allocation_weights(positions, group_by="sector")
    weights = {r.key: r.weight for r in rows}
    assert weights["Tech"] == Decimal("0.8")
    assert weights["Energy"] == Decimal("0.2")


def test_group_by_industry_unclassified_bucket() -> None:
    positions = [
        PositionValue(ticker="AAPL", market_value=Decimal("500"), industry="Hardware"),
        PositionValue(ticker="???", market_value=Decimal("500")),
    ]
    rows = allocation_weights(positions, group_by="industry")
    keys = {r.key for r in rows}
    assert keys == {"Hardware", "UNCLASSIFIED"}


def test_invalid_group_by_raises() -> None:
    with pytest.raises(ValueError):
        allocation_weights([PositionValue(ticker="A", market_value=Decimal("1"))], group_by="country")


def test_zero_total_value_yields_zero_weights() -> None:
    positions = [
        PositionValue(ticker="A", market_value=Decimal("0")),
        PositionValue(ticker="B", market_value=Decimal("0")),
    ]
    rows = allocation_weights(positions)
    assert all(r.weight == Decimal("0") for r in rows)
