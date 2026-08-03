"""Unit tests for broker-statement parsing (Robinhood CSV).

Pure translation tests: bytes in, typed transactions out. No DB, no network. We
assert the mapping, the money-cell cleaning (symbols / commas / parentheses), and
that unmapped rows surface as warnings instead of vanishing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.portfolio.schemas import StatementFormat, TransactionType
from app.portfolio.statements import (
    RobinhoodCsvParser,
    StatementParseError,
    get_parser,
)

_HEADER = "Activity Date,Instrument,Trans Code,Quantity,Price,Amount\n"

# The exact column set Robinhood's account-activity export produces.
_RH_HEADER = (
    "Activity Date,Process Date,Settle Date,Instrument,Description,"
    "Trans Code,Quantity,Price,Amount\n"
)


def _csv(*rows: str) -> bytes:
    return (_HEADER + "".join(row + "\n" for row in rows)).encode("utf-8")


def _rh_csv(*rows: str) -> bytes:
    return (_RH_HEADER + "".join(row + "\n" for row in rows)).encode("utf-8")


def test_parses_real_robinhood_column_layout() -> None:
    """The full 9-column export parses, keying off Activity Date (not Settle Date)."""

    data = _rh_csv(
        '03/04/2021,03/05/2021,03/08/2021,AAPL,Apple Inc. Common Stock,Sell,4,$150.00,$600.00',
        '01/02/2020,01/03/2020,01/06/2020,AAPL,Apple Inc. Common Stock,Buy,10,$100.00,"($1,000.00)"',
    )
    parsed = RobinhoodCsvParser().parse(data)

    assert parsed.warnings == ()
    assert len(parsed.transactions) == 2
    by_type = {t.type: t for t in parsed.transactions}
    buy = by_type[TransactionType.BUY]
    assert buy.trade_date == date(2020, 1, 2)  # Activity Date, not Settle Date
    assert buy.quantity == Decimal("10")
    assert buy.price == Decimal("100.00")
    sell = by_type[TransactionType.SELL]
    assert sell.trade_date == date(2021, 3, 4)


def test_reverse_chronological_rows_are_accepted() -> None:
    """Robinhood exports newest-first; the ledger/calculators sort by date anyway."""

    parsed = RobinhoodCsvParser().parse(
        _rh_csv(
            "03/04/2021,03/05/2021,03/08/2021,MSFT,Microsoft,Sell,2,$200.00,$400.00",
            "01/02/2020,01/03/2020,01/06/2020,MSFT,Microsoft,Buy,5,$100.00,($500.00)",
        )
    )
    dates = [t.trade_date for t in parsed.transactions]
    assert dates == [date(2021, 3, 4), date(2020, 1, 2)]  # file order preserved


def test_price_is_derived_from_amount_when_blank() -> None:
    """A fill with no Price still yields a correct cost basis via Amount/Quantity."""

    parsed = RobinhoodCsvParser().parse(
        _rh_csv("01/02/2020,01/03/2020,01/06/2020,VTI,Vanguard,Buy,2,,($250.00)")
    )
    (txn,) = parsed.transactions
    assert txn.price == Decimal("125")


def test_withholding_tax_becomes_a_fee() -> None:
    parsed = RobinhoodCsvParser().parse(
        _rh_csv("06/01/2022,06/01/2022,06/01/2022,BTI,Foreign tax,DTAX,,,($1.50)")
    )
    (txn,) = parsed.transactions
    assert txn.type is TransactionType.FEE
    assert txn.amount == Decimal("1.50")


def test_option_and_transfer_rows_warn_with_reasons() -> None:
    parsed = RobinhoodCsvParser().parse(
        _rh_csv(
            "06/01/2022,06/01/2022,06/01/2022,AAPL,Call option,BTO,1,$2.00,($200.00)",
            "06/02/2022,06/02/2022,06/02/2022,,ACH Deposit,ACH,,,$500.00",
            "06/03/2022,06/03/2022,06/03/2022,TSLA,3-for-1 split,SPL,20,,",
        )
    )
    assert parsed.transactions == ()
    joined = " | ".join(parsed.warnings).lower()
    assert "options trade" in joined
    assert "cash transfer" in joined
    assert "split" in joined  # tells the user to enter it manually


def test_rejects_a_csv_that_is_not_an_activity_export() -> None:
    with pytest.raises(StatementParseError):
        RobinhoodCsvParser().parse(b"foo,bar\n1,2\n")


def test_parses_buy_and_sell_rows() -> None:
    data = _csv(
        "01/02/2020,AAPL,Buy,10,$100.00,$1000.00",
        "03/04/2021,AAPL,Sell,4,$150.00,$600.00",
    )
    parsed = RobinhoodCsvParser().parse(data)

    assert parsed.source_format is StatementFormat.ROBINHOOD_CSV
    assert [t.type for t in parsed.transactions] == [
        TransactionType.BUY,
        TransactionType.SELL,
    ]
    buy = parsed.transactions[0]
    assert buy.ticker == "AAPL"
    assert buy.trade_date == date(2020, 1, 2)
    assert buy.quantity == Decimal("10")
    assert buy.price == Decimal("100.00")
    assert buy.currency == "USD"
    assert parsed.warnings == ()


def test_dividend_amount_strips_symbols_and_commas() -> None:
    # A real export quotes cells containing commas; assert we strip $ and , cleanly.
    parsed = RobinhoodCsvParser().parse(
        (_HEADER + '06/01/2022,MSFT,CDIV,,,"$1,234.50"\n').encode("utf-8")
    )
    (txn,) = parsed.transactions
    assert txn.type is TransactionType.DIVIDEND
    assert txn.amount == Decimal("1234.50")


def test_unknown_code_becomes_warning_not_transaction() -> None:
    parsed = RobinhoodCsvParser().parse(_csv("06/01/2022,,ACH,,,$500.00"))
    assert parsed.transactions == ()
    assert len(parsed.warnings) == 1
    assert "cash transfer" in parsed.warnings[0].lower()


def test_completely_unrecognized_code_warns() -> None:
    parsed = RobinhoodCsvParser().parse(_csv("06/01/2022,AAPL,ZZZZ,,,$5.00"))
    assert parsed.transactions == ()
    assert "unrecognized transaction code" in parsed.warnings[0].lower()


def test_missing_ticker_warns() -> None:
    parsed = RobinhoodCsvParser().parse(_csv("06/01/2022,,Buy,1,$10,$10"))
    assert parsed.transactions == ()
    assert "missing instrument" in parsed.warnings[0].lower()


def test_bad_date_warns() -> None:
    parsed = RobinhoodCsvParser().parse(_csv("not-a-date,AAPL,Buy,1,$10,$10"))
    assert parsed.transactions == ()
    assert "date" in parsed.warnings[0].lower()


def test_currency_is_injectable() -> None:
    parsed = RobinhoodCsvParser(currency="inr").parse(
        _csv("01/02/2020,INFY,Buy,5,100,500")
    )
    assert parsed.transactions[0].currency == "INR"


def test_non_utf8_bytes_raise_parse_error() -> None:
    with pytest.raises(StatementParseError):
        RobinhoodCsvParser().parse(b"\xff\xfe\x00bad")


def test_get_parser_returns_robinhood() -> None:
    parser = get_parser(StatementFormat.ROBINHOOD_CSV)
    assert parser.source_format is StatementFormat.ROBINHOOD_CSV
