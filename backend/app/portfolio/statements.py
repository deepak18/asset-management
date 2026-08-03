"""Broker statement parsing — decode an uploaded CSV into ledger transactions.

Why a dedicated seam
--------------------
Parsing is a *pure translation*: raw bytes in, typed :class:`Transaction` objects
out. Keeping it behind a ``StatementParser`` interface (structural ``Protocol``)
means adding a new broker (Fidelity, Schwab, a generic CSV) is a new implementation,
not a change to the import endpoint or the persistence layer. The endpoint depends
on the interface, never on a concrete format.

Why we don't trust the browser's Content-Type
----------------------------------------------
A file upload's declared MIME type is attacker/OS-controlled metadata — a browser
will happily label a ``.csv`` as ``application/octet-stream``, and a malicious
client can send any string. So format selection is explicit (a request parameter),
and validation is *content-based*: we decode the bytes and confirm the expected
header columns actually parse. Trusting ``content_type`` alone would be a spoofable
security and correctness hole.

Money precision
---------------
Broker CSVs render money as display strings (``"$1,234.50"``, ``"(12.00)"`` for
negatives). We strip the presentation and parse straight into :class:`Decimal` so no
binary-float drift ever enters the ledger.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.portfolio.schemas import (
    ParsedStatement,
    StatementFormat,
    Transaction,
    TransactionType,
)


class StatementParseError(ValueError):
    """Raised when a statement's bytes cannot be decoded into a usable table."""


class StatementParser(Protocol):
    """Decode raw statement bytes into a typed :class:`ParsedStatement`."""

    @property
    def source_format(self) -> StatementFormat:
        """The broker/layout this parser understands."""
        ...

    def parse(self, data: bytes) -> ParsedStatement:
        """Decode ``data`` into ledger transactions (+ warnings for unmapped rows)."""
        ...


def _clean_decimal(raw: str) -> Decimal | None:
    """Parse a broker money/quantity cell into an exact ``Decimal`` (or ``None``).

    Handles the common display cruft: currency symbols, thousands separators, and
    parenthesized negatives (``"($12.00)"`` -> ``-12.00``). Blank cells map to
    ``None`` so callers can distinguish "absent" from "zero".
    """

    text = raw.strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return -value if negative else value


def _parse_date(raw: str) -> date | None:
    """Parse a broker date cell, tolerating the few common US layouts."""

    text = raw.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _pick(row: dict[str, str], *names: str) -> str:
    """Return the first present, case-insensitively matched column value.

    Always returns a ``str``. Two real-world quirks force the defensiveness:
    a **short row** (broker exports end with a stray ``""`` line) makes
    ``DictReader`` fill the missing columns with ``None``, and a **long row** (the
    trailing legal disclaimer carries an extra field) parks the surplus under a
    ``None`` key. Both would otherwise blow up on attribute access.
    """

    lowered = {
        key.strip().lower(): value
        for key, value in row.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return ""


class RobinhoodCsvParser:
    """Parse a Robinhood account-activity CSV export.

    Expected (case-insensitive) columns, matching Robinhood's export exactly:
    ``Activity Date``, ``Process Date``, ``Settle Date``, ``Instrument``,
    ``Description``, ``Trans Code``, ``Quantity``, ``Price``, ``Amount``.
    We key off ``Activity Date`` (the trade date, which is what cost-basis and XIRR
    care about) rather than settlement, and tolerate the alternate header spellings
    other brokers use.

    Only ``Trans Code`` values that map cleanly onto a ledger event are imported.
    Everything else — options legs, ACH transfers, interest, corporate actions — is
    reported in ``warnings`` with the reason and the row's description, so nothing
    is silently dropped and you can see exactly what still needs manual entry.

    Robinhood trades settle in USD, so a single ``currency`` is applied to every
    row; it is injectable to keep the parser reusable for multi-currency brokers.
    """

    # Trades: quantity + per-share price.
    _TRADE_CODES = {
        "buy": TransactionType.BUY,
        "sell": TransactionType.SELL,
    }

    # Cash dividends: the 'Amount' column carries the cash received.
    _DIVIDEND_CODES = {"cdiv", "dividend"}

    # Charges tied to a specific instrument (withholding tax, ADR/foreign fees).
    # These reduce realized P&L, so importing them keeps returns honest.
    _FEE_CODES = {"dtax", "afee", "dfee"}

    # Transfers. Context-dependent: with an instrument + quantity these move a
    # *position* between accounts (no cost basis in the export); otherwise cash.
    _TRANSFER_CODES = {"itrf", "ach", "rtp", "wire", "aftr"}

    # Recognized but not representable as a ledger event. Mapped to a plain-English
    # reason so the warning tells you what to do, not just that something failed.
    _UNSUPPORTED_CODES = {
        "sto": "options trade (sell to open) — not modeled",
        "bto": "options trade (buy to open) — not modeled",
        "stc": "options trade (sell to close) — not modeled",
        "btc": "options trade (buy to close) — not modeled",
        "oexp": "option expiration — not modeled",
        "oasgn": "option assignment — not modeled",
        "aexp": "option exercise — not modeled",
        "spl": "stock split — enter manually as a SPLIT with its ratio",
        "spr": "reverse split — enter manually as a SPLIT with its ratio",
        "soff": "spin-off — enter manually",
        "rec": "share reclassification — enter manually",
        "int": "interest — no security position affected",
        "gold": "subscription fee — no security position affected",
        "mint": "cash sweep interest — no security position affected",
    }

    def __init__(self, currency: str = "USD") -> None:
        self._currency = currency.upper()

    @property
    def source_format(self) -> StatementFormat:
        return StatementFormat.ROBINHOOD_CSV

    def parse(self, data: bytes) -> ParsedStatement:
        try:
            # utf-8-sig transparently strips a BOM many exporters prepend.
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise StatementParseError("statement is not valid UTF-8 text") from exc

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise StatementParseError("statement has no header row")

        # Content-based validation: confirm the columns we actually need are present
        # instead of trusting the upload's declared type or the file extension.
        headers = {(h or "").strip().lower() for h in reader.fieldnames}
        if "trans code" not in headers or "instrument" not in headers:
            raise StatementParseError(
                "not a Robinhood activity CSV: expected 'Trans Code' and "
                "'Instrument' columns"
            )

        transactions: list[Transaction] = []
        warnings: list[str] = []

        for row in reader:
            # reader.line_num is the *physical* line just consumed. Robinhood wraps
            # multi-line values (e.g. "Netflix\nCUSIP: 64110L106") inside quoted
            # fields, so one record can span several lines — a manual counter would
            # drift and point at the wrong row in every warning.
            line_no = reader.line_num

            code = _pick(row, "Trans Code", "Type", "Action").strip().lower()
            if not code:
                continue  # blank spacer line, trailing "" row, or legal disclaimer

            description = _pick(row, "Description").strip()
            ticker = _pick(row, "Instrument", "Symbol", "Ticker").strip().upper()
            quantity_raw = _pick(row, "Quantity")

            reason = self._unsupported_reason(code, ticker, quantity_raw)
            if reason is not None:
                warnings.append(self._warn(line_no, code, reason, description))
                continue

            ttype = self._resolve_type(code)
            if ttype is None:
                warnings.append(
                    self._warn(line_no, code, "unrecognized transaction code", description)
                )
                continue

            if not ticker:
                warnings.append(
                    self._warn(line_no, code, "missing instrument/ticker", description)
                )
                continue

            trade_date = _parse_date(
                _pick(row, "Activity Date", "Trade Date", "Date", "Process Date")
            )
            if trade_date is None:
                warnings.append(
                    self._warn(line_no, code, "unparseable or missing date", description)
                )
                continue

            txn = self._build_txn(line_no, code, ttype, ticker, trade_date, row, warnings)
            if txn is not None:
                transactions.append(txn)

        return ParsedStatement(
            source_format=self.source_format,
            transactions=tuple(transactions),
            warnings=tuple(warnings),
        )

    def _unsupported_reason(
        self, code: str, ticker: str, quantity_raw: str
    ) -> str | None:
        """Return why ``code`` can't become a ledger event, or ``None`` if it can.

        Most codes map statically, but transfers are **context-dependent**: the same
        ``ITRF`` code marks both a cash movement and an incoming *share position*.
        A transferred-in position carries no price in the export, so importing it
        would book a zero-cost lot and massively overstate gains — we refuse and
        point the user at the position-snapshot form, where the real cost basis
        can be entered.
        """

        if code in self._TRANSFER_CODES:
            quantity = _clean_decimal(quantity_raw)
            if ticker and quantity is not None and quantity > 0:
                return (
                    "position transferred in — the export carries no cost basis, "
                    "so add it with the position-snapshot form instead"
                )
            return "cash transfer — not a security transaction"

        return self._UNSUPPORTED_CODES.get(code)

    @staticmethod
    def _warn(line_no: int, code: str, reason: str, description: str) -> str:
        """Build a warning that says which row, which code, and why it was skipped.

        Descriptions arrive with embedded newlines ("Netflix\\nCUSIP: 64110L106");
        collapse them so each warning stays a single readable line in the UI.
        """

        flat = " ".join(description.split())
        suffix = f" ({flat})" if flat else ""
        return f"row {line_no}: skipped {code.upper()} — {reason}{suffix}"

    def _resolve_type(self, code: str) -> TransactionType | None:
        if code in self._TRADE_CODES:
            return self._TRADE_CODES[code]
        if code in self._DIVIDEND_CODES:
            return TransactionType.DIVIDEND
        if code in self._FEE_CODES:
            return TransactionType.FEE
        return None

    def _build_txn(
        self,
        line_no: int,
        code: str,
        ttype: TransactionType,
        ticker: str,
        trade_date: date,
        row: dict[str, str],
        warnings: list[str],
    ) -> Transaction | None:
        """Map one validated row to a ledger transaction (or warn + skip)."""

        quantity = _clean_decimal(_pick(row, "Quantity")) or Decimal(0)
        price = _clean_decimal(_pick(row, "Price")) or Decimal(0)
        amount = _clean_decimal(_pick(row, "Amount")) or Decimal(0)

        if ttype in (TransactionType.BUY, TransactionType.SELL):
            if quantity <= 0:
                warnings.append(
                    self._warn(line_no, code, "needs a positive quantity", "")
                )
                return None
            if price <= 0:
                # Some rows (dividend reinvestments, fractional fills) leave Price
                # blank but still report the total Amount. Deriving the per-share
                # price keeps the lot's cost basis correct instead of recording a
                # zero-cost position.
                if amount == 0:
                    warnings.append(
                        self._warn(line_no, code, "no usable price or amount", "")
                    )
                    return None
                price = abs(amount) / quantity
            return Transaction(
                ticker=ticker,
                type=ttype,
                trade_date=trade_date,
                currency=self._currency,
                quantity=quantity,
                price=price,
            )

        # DIVIDEND / FEE: cash-only events carried in 'Amount'. Robinhood renders
        # outflows parenthesized; the ledger stores magnitudes and applies the sign
        # by transaction type, so we normalize to a positive amount here.
        if amount == 0:
            warnings.append(self._warn(line_no, code, "zero or missing amount", ""))
            return None
        return Transaction(
            ticker=ticker,
            type=ttype,
            trade_date=trade_date,
            currency=self._currency,
            amount=abs(amount),
        )


def get_parser(source_format: StatementFormat) -> StatementParser:
    """Return the parser for a requested statement format.

    A tiny registry today (one broker); the point is that the import endpoint asks
    for a parser *by format* and never hard-codes a concrete class.
    """

    if source_format is StatementFormat.ROBINHOOD_CSV:
        return RobinhoodCsvParser()
    raise StatementParseError(f"no parser for format {source_format!r}")
