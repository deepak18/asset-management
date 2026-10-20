from datetime import date
from decimal import Decimal

import pytest

from app.core.currency import FxRateTable
from app.portfolio.calculators import cost_basis_fifo
from app.portfolio.reconciliation import correction_transaction, infer_splits
from app.portfolio.schemas import (
    DataGap,
    ImportIssue,
    ParsedStatement,
    PositionSnapshot,
    StatementFormat,
    Transaction,
    TransactionType,
    UnresolvedKind,
    UnresolvedResolution,
)
from app.portfolio.statements import RobinhoodCsvParser


def _parsed(
    quantity: str = "0.16703", delta: str = "3.17357", code: str = "SPL"
) -> ParsedStatement:
    return ParsedStatement(
        source_format=StatementFormat.ROBINHOOD_CSV,
        transactions=(
            Transaction(
                ticker="BKNG",
                type=TransactionType.BUY,
                trade_date=date(2020, 1, 1),
                currency="USD",
                quantity=Decimal(quantity),
                price=Decimal("100"),
            ),
        ),
        warnings=("row 3: skipped SPL — ratio unknown",),
        unresolved_items=(
            ImportIssue(
                kind=UnresolvedKind.SPLIT_RATIO_UNKNOWN,
                source_line=3,
                ticker="BKNG",
                trade_date=date(2026, 4, 6),
                currency="USD",
                quantity=Decimal(delta),
                code=code,
                data_gaps=(DataGap.SPLIT_RATIO,),
            ),
        ),
    )


def test_earlier_buy_does_not_prove_history_complete() -> None:
    parsed = _parsed()
    assert infer_splits(parsed, False) == parsed


@pytest.mark.parametrize(
    ("quantity", "delta", "code", "ratio"),
    [
        ("0.16703", "3.17357", "SPL", "20"),
        ("10", "9", "SPR", "0.1"),
    ],
)
def test_confirmed_history_fractional_and_reverse_split(
    quantity: str, delta: str, code: str, ratio: str
) -> None:
    parsed = _parsed(quantity, delta, code)
    result = infer_splits(parsed, True)
    assert result.unresolved_items == ()
    assert result.transactions[-1].split_ratio == Decimal(ratio)
    before = cost_basis_fifo(list(parsed.transactions), FxRateTable(base_currency="USD"))
    after = cost_basis_fifo(list(result.transactions), FxRateTable(base_currency="USD"))
    assert before.open_cost_basis_base == after.open_cost_basis_base
    assert after.open_quantity == Decimal(quantity) * Decimal(ratio)
    assert not any("skipped" in w for w in result.warnings)


@pytest.mark.parametrize(("quantity", "delta"), [("0", "20"), ("1", "1.3"), ("1", "-2")])
def test_ambiguous_ratios_remain_unresolved(quantity: str, delta: str) -> None:
    assert len(infer_splits(_parsed(quantity, delta), True).unresolved_items) == 1


def test_same_day_trade_blocks_inference() -> None:
    parsed = _parsed()
    buy = parsed.transactions[0].model_copy(update={"trade_date": date(2026, 4, 6)})
    assert infer_splits(parsed.model_copy(update={"transactions": (buy,)}), True).unresolved_items


def test_prior_unresolved_transfer_blocks_split() -> None:
    parsed = _parsed()
    transfer = ImportIssue(
        kind=UnresolvedKind.TRANSFER_IN_NO_COST_BASIS,
        source_line=2,
        ticker="BKNG",
        trade_date=date(2019, 1, 1),
        quantity=Decimal("1"),
        data_gaps=(DataGap.COST_BASIS,),
    )
    result = infer_splits(
        parsed.model_copy(update={"unresolved_items": (transfer, *parsed.unresolved_items)}), True
    )
    assert len(result.unresolved_items) == 2


def test_parser_returns_typed_items_without_price_availability_gaps() -> None:
    data = (
        b"Activity Date,Instrument,Description,Trans Code,Quantity,Price,Amount\n"
        b"01/01/2020,AAPL,transfer,ITRF,3,,\n"
        b"01/02/2020,AAPL,split,SPL,3,,\n"
        b"01/03/2020,AAPL,trade,Buy,1,,\n"
        b"01/04/2020,AAPL,option,BTO,1,$1,$1\n"
    )
    parsed = RobinhoodCsvParser().parse(data)
    assert [item.kind for item in parsed.unresolved_items] == [
        UnresolvedKind.TRANSFER_IN_NO_COST_BASIS,
        UnresolvedKind.SPLIT_RATIO_UNKNOWN,
        UnresolvedKind.MISSING_DATA,
        UnresolvedKind.UNSUPPORTED_ROW,
    ]
    assert parsed.unresolved_items[0].data_gaps == (DataGap.COST_BASIS,)
    assert len(parsed.warnings) == 4


def test_transfer_correction_uses_supplied_basis_and_source_date() -> None:
    item = ImportIssue(
        kind=UnresolvedKind.TRANSFER_IN_NO_COST_BASIS,
        source_line=2,
        ticker="AAPL",
        trade_date=date(2020, 1, 1),
        currency="USD",
        quantity=Decimal("3"),
    )
    resolution = UnresolvedResolution(
        snapshot=PositionSnapshot(
            ticker="AAPL", currency="USD", quantity=Decimal("3"), total_cost_basis=Decimal("300")
        )
    )
    txn = correction_transaction(item, resolution)
    assert txn.price == Decimal("100") and txn.trade_date == item.trade_date
    with pytest.raises(ValueError, match="ticker"):
        correction_transaction(
            item,
            UnresolvedResolution(
                snapshot=resolution.snapshot.model_copy(update={"ticker": "TYPO"})
            ),
        )
