"""Pure Vanguard source parsing, reconciliation and state-bound review policy."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from hashlib import sha256
from itertools import groupby
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from app.portfolio.accounts import (
    AccountConflict,
    AccountValidationError,
    Amount,
    Contract,
    Currency,
    SecurityInfo,
    canonical_decimal,
)

HOLDINGS_HEADER = "Plan Number,Plan Name,Fund Name,Shares,Price,Total Value,"
ACTIVITY_HEADER = (
    "Account Number,Trade Date,Run Date,Transaction Activity,Transaction Description,"
    "Investment Name,Share Price,Transaction Shares,Dollar Amount,"
)
MAX_ROWS = 50000
SignedAmount = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=28, decimal_places=10)]


class ImportOptions(Contract):
    as_of: date
    currency: Currency
    history_complete: bool = False


class SourceLine(Contract):
    checksum: str
    source_line: int
    source_reference: str
    raw_fields: tuple[str, ...]


class HoldingFact(SourceLine):
    plan_number: str
    plan_name: str
    fund_name: str
    quantity: Amount
    reported_price: Amount
    reported_value: Amount
    cost_basis: None = None
    unrealized_pnl: None = None


class ActivityKind(StrEnum):
    CONTRIBUTION = "CONTRIBUTION"
    REINVESTMENT = "REINVESTMENT"
    UNSUPPORTED = "UNSUPPORTED"


class ActivityFact(SourceLine):
    account_number: str
    trade_date: date
    run_date: date
    code: str
    description: str
    fund_name: str
    price: Amount
    quantity: SignedAmount
    amount: SignedAmount
    kind: ActivityKind
    fingerprint: str
    external_contribution: Decimal | None
    dividend_amount: Decimal | None


class ParsedVanguard(Contract):
    checksum: str
    plan_number: str
    plan_name: str
    account_number: str
    holdings: tuple[HoldingFact, ...]
    activity: tuple[ActivityFact, ...]


class IssueCode(StrEnum):
    UNSUPPORTED_ACTIVITY = "UNSUPPORTED_ACTIVITY"
    INVALID_MOVEMENT = "INVALID_MOVEMENT"
    FUTURE_TRADE = "FUTURE_TRADE"
    NEGATIVE_PRIOR_BALANCE = "NEGATIVE_PRIOR_BALANCE"
    INCOMPLETE_HISTORY = "INCOMPLETE_HISTORY"
    COMPLETE_HISTORY_MISMATCH = "COMPLETE_HISTORY_MISMATCH"


class ImportIssue(Contract):
    code: IssueCode
    blocking: bool
    fund_name: str | None = None
    source_line: int | None = None
    message: str


class Reconciliation(Contract):
    fund_name: str
    closing_units: Decimal
    net_supported_movement: Decimal | None
    implied_prior_units: Decimal | None
    status: Literal["HISTORY_INCOMPLETE", "SHARES_RECONCILED", "BLOCKED"]
    performance_calculable: Literal[False] = False


class FundMapping(Contract):
    fund_name: str
    alias_value: str
    security_id: int | None
    ticker: str | None
    status: Literal["MAPPED", "WILL_CREATE_UNKNOWN"]


class ImportState(Contract):
    portfolio_id: int
    base_currency: str
    external_account_id: str | None
    custodian: str | None
    account_type: str
    securities: tuple[SecurityInfo, ...]
    imports: tuple[str, ...]
    valuations: tuple[str, ...]
    event_fingerprints: tuple[str, ...]


class RetirementPreview(Contract):
    portfolio_id: int
    preview_token: str
    options: ImportOptions
    source: ParsedVanguard
    funds: tuple[FundMapping, ...]
    reported_total: Decimal
    cost_basis: None = None
    unrealized_pnl: None = None
    money_weighted_return: None = None
    issues: tuple[ImportIssue, ...]
    reconciliation: tuple[Reconciliation, ...]
    can_commit: bool


class RetirementImport(Contract):
    id: int
    portfolio_id: int
    valuation_id: int
    imported_at: datetime
    storage_key: str
    status: Literal["COMMITTED"] = "COMMITTED"
    preview: RetirementPreview


class ObservedActivity(Contract):
    id: int
    import_id: int
    portfolio_id: int
    security_id: int
    currency: Currency
    source_code: Literal["VANGUARD"] = "VANGUARD"
    fact: ActivityFact


def normalized_account(value: str) -> str:
    if not re.fullmatch(r"[0-9]{1,120}", value):
        raise AccountValidationError("plan/account identifiers must contain only digits")
    return value.lstrip("0") or "0"


def fund_alias(plan: str, account: str, fund_name: str) -> str:
    # Hash the exact name to fit the shared alias column without conflating plans/classes.
    scope = json.dumps((normalized_account(plan), normalized_account(account), fund_name))
    return "plan-account-fund:" + sha256(scope.encode()).hexdigest()


def _number(cell: str) -> Decimal:
    if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", cell):
        raise AccountValidationError("invalid decimal cell (finite plain decimal required)")
    return Decimal(cell)


def _date(cell: str) -> date:
    if not re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", cell):
        raise AccountValidationError("file dates must be MM/DD/YYYY")
    try:
        return datetime.strptime(cell, "%m/%d/%Y").date()
    except ValueError as exc:
        raise AccountValidationError("invalid file date") from exc


def _fingerprint(fields: tuple[str, ...]) -> str:
    return sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def parse_vanguard(content: bytes) -> ParsedVanguard:
    """Require both exact ordered headers; never interpret malformed headers as data."""
    checksum = sha256(content).hexdigest()
    holdings: list[HoldingFact] = []
    activity: list[ActivityFact] = []
    section = 0
    count = 0
    try:
        reader = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        previous_line = 0
        for raw in reader:
            line = previous_line + 1
            previous_line = reader.line_num
            cells = list(raw)
            while cells and cells[-1] == "":
                cells.pop()
            if not cells:
                continue
            count += 1
            if count > MAX_ROWS:
                raise AccountValidationError(f"CSV exceeds {MAX_ROWS} nonblank rows")
            fields = tuple(cells)
            if fields == tuple(HOLDINGS_HEADER.rstrip(",").split(",")):
                if section != 0:
                    raise AccountValidationError("duplicate or reordered holdings section")
                section = 1
                continue
            if fields == tuple(ACTIVITY_HEADER.rstrip(",").split(",")):
                if section != 1 or not holdings:
                    raise AccountValidationError("activity must follow nonempty holdings section")
                section = 2
                continue
            if any(
                c in {"Plan Number", "Account Number", "Fund Name", "Trade Date"} for c in fields
            ):
                raise AccountValidationError(f"malformed section header at line {line}")
            provenance = SourceLine(
                checksum=checksum,
                source_line=line,
                source_reference=f"sha256:{checksum}:line:{line}",
                raw_fields=tuple(raw),
            )
            if section == 1 and len(fields) == 6:
                plan, plan_name, name, units, price, value = fields
                normalized_account(plan)
                if not plan_name.strip() or not name.strip() or len(name) > 240:
                    raise AccountValidationError("plan/fund names must be nonempty and bounded")
                holdings.append(
                    HoldingFact(
                        **provenance.model_dump(),
                        plan_number=plan,
                        plan_name=plan_name,
                        fund_name=name,
                        quantity=_number(units),
                        reported_price=_number(price),
                        reported_value=_number(value),
                    )
                )
            elif section == 2 and len(fields) == 9:
                account, trade, run, code, description, name, price, units, amount = fields
                normalized_account(account)
                if not name.strip() or len(name) > 240 or not code or not description:
                    raise AccountValidationError("activity name/code/description required")
                trade_date, run_date = _date(trade), _date(run)
                if run_date < trade_date:
                    raise AccountValidationError("run date precedes trade date")
                quantity, cash, share_price = _number(units), _number(amount), _number(price)
                kind = {
                    "114001": ActivityKind.CONTRIBUTION,
                    "219004": ActivityKind.REINVESTMENT,
                }.get(code, ActivityKind.UNSUPPORTED)
                fingerprint = _fingerprint(
                    (
                        normalized_account(account),
                        trade_date.isoformat(),
                        run_date.isoformat(),
                        code,
                        description,
                        name,
                        canonical_decimal(share_price),
                        canonical_decimal(quantity),
                        canonical_decimal(cash),
                    )
                )
                activity.append(
                    ActivityFact(
                        **provenance.model_dump(),
                        account_number=account,
                        trade_date=trade_date,
                        run_date=run_date,
                        code=code,
                        description=description,
                        fund_name=name,
                        price=share_price,
                        quantity=quantity,
                        amount=cash,
                        kind=kind,
                        fingerprint=fingerprint,
                        external_contribution=cash if kind == ActivityKind.CONTRIBUTION else None,
                        dividend_amount=cash if kind == ActivityKind.REINVESTMENT else None,
                    )
                )
            else:
                raise AccountValidationError(f"unexpected CSV row at line {line}")
    except (UnicodeError, csv.Error, ValidationError) as exc:
        raise AccountValidationError(f"invalid Vanguard CSV: {exc}") from exc
    if section != 2 or not activity:
        raise AccountValidationError("both holdings and nonempty activity sections required")
    plans = {(h.plan_number, h.plan_name) for h in holdings}
    accounts = {normalized_account(a.account_number) for a in activity}
    if len(plans) != 1 or len(accounts) != 1:
        raise AccountValidationError(
            "exactly one plan and one normalized activity account required"
        )
    plan, plan_name = next(iter(plans))
    if normalized_account(plan) != next(iter(accounts)):
        raise AccountConflict("plan and activity account do not match")
    if len({h.fund_name for h in holdings}) != len(holdings):
        raise AccountValidationError("duplicate holding fund")
    return ParsedVanguard(
        checksum=checksum,
        plan_number=plan,
        plan_name=plan_name,
        account_number=activity[0].account_number,
        holdings=tuple(holdings),
        activity=tuple(activity),
    )


def build_preview(
    parsed: ParsedVanguard,
    options: ImportOptions,
    state: ImportState,
) -> RetirementPreview:
    if options.currency != "USD" or options.currency != state.base_currency:
        raise AccountValidationError(
            "USD matching the portfolio currency is required; FX unavailable"
        )
    if state.external_account_id is not None:
        try:
            bound_account = normalized_account(state.external_account_id)
        except AccountValidationError as exc:
            raise AccountConflict(
                "bound portfolio account is not a Vanguard numeric account"
            ) from exc
        if bound_account != normalized_account(parsed.account_number):
            raise AccountConflict("source account differs from bound portfolio account")
    if parsed.checksum in state.imports:
        raise AccountConflict("duplicate checksum: this file is already imported")
    if set(state.event_fingerprints).intersection(a.fingerprint for a in parsed.activity):
        raise AccountConflict(
            "ambiguous overlapping source activity; combine nonoverlapping export periods"
        )
    funds: list[FundMapping] = []
    reconciliations: list[Reconciliation] = []
    issues: list[ImportIssue] = []
    if not options.history_complete:
        issues.append(
            ImportIssue(
                code=IssueCode.INCOMPLETE_HISTORY,
                blocking=False,
                message="Partial history: implied opening units are diagnostics only.",
            )
        )
    # Typed lookup collections keep a bounded large export linear after sorting.
    by_fund: dict[str, tuple[ActivityFact, ...]] = {
        name: tuple(events)
        for name, events in groupby(
            sorted(parsed.activity, key=lambda event: event.fund_name),
            key=lambda event: event.fund_name,
        )
    }
    holdings_by_fund: dict[str, HoldingFact] = {h.fund_name: h for h in parsed.holdings}
    security_by_alias: dict[str, SecurityInfo] = {}
    for candidate in state.securities:
        for source_alias in candidate.aliases:
            if source_alias.source_code == "VANGUARD":
                existing = security_by_alias.get(source_alias.value)
                if existing is not None and existing.id != candidate.id:
                    raise AccountConflict("incompatible source security mapping")
                security_by_alias[source_alias.value] = candidate
    used_ids: set[int] = set()
    names = sorted(holdings_by_fund.keys() | by_fund.keys())
    with localcontext() as context:
        context.prec = 60
        for name in names:
            alias = fund_alias(parsed.plan_number, parsed.account_number, name)
            security = security_by_alias.get(alias)
            if security and security.currency != options.currency:
                raise AccountConflict("incompatible source security mapping")
            if security and security.id in used_ids:
                raise AccountConflict("multiple source funds map to one security; review mappings")
            if security:
                used_ids.add(security.id)
            funds.append(
                FundMapping(
                    fund_name=name,
                    alias_value=alias,
                    security_id=security.id if security else None,
                    ticker=security.ticker if security else None,
                    status="MAPPED" if security else "WILL_CREATE_UNKNOWN",
                )
            )
            events = by_fund.get(name, ())
            holding = holdings_by_fund.get(name)
            closing = holding.quantity if holding else Decimal(0)
            issue_start = len(issues)
            for event in events:
                if event.kind == ActivityKind.UNSUPPORTED:
                    issues.append(
                        ImportIssue(
                            code=IssueCode.UNSUPPORTED_ACTIVITY,
                            blocking=True,
                            fund_name=name,
                            source_line=event.source_line,
                            message=f"Unsupported code {event.code}; row retained; commit blocked.",
                        )
                    )
                elif event.quantity <= 0 or event.amount < 0:
                    issues.append(
                        ImportIssue(
                            code=IssueCode.INVALID_MOVEMENT,
                            blocking=True,
                            fund_name=name,
                            source_line=event.source_line,
                            message="Acquisitions require positive shares and nonnegative dollars.",
                        )
                    )
                if event.trade_date > options.as_of:
                    issues.append(
                        ImportIssue(
                            code=IssueCode.FUTURE_TRADE,
                            blocking=True,
                            fund_name=name,
                            source_line=event.source_line,
                            message="Trade date exceeds explicit as_of.",
                        )
                    )
            unknown = any(e.kind == ActivityKind.UNSUPPORTED for e in events)
            movement: Decimal | None = None
            if not unknown:
                movement = Decimal(0)
                for event in events:
                    movement += event.quantity
            prior: Decimal | None = None if movement is None else closing - movement
            if prior is not None and prior < 0:
                issues.append(
                    ImportIssue(
                        code=IssueCode.NEGATIVE_PRIOR_BALANCE,
                        blocking=True,
                        fund_name=name,
                        message="Negative implied opening units; supply a reconciled export.",
                    )
                )
            if options.history_complete and (prior is None or prior != 0):
                issues.append(
                    ImportIssue(
                        code=IssueCode.COMPLETE_HISTORY_MISMATCH,
                        blocking=True,
                        fund_name=name,
                        message="Complete history must explain closing units with known events.",
                    )
                )
            blocked = any(i.blocking for i in issues[issue_start:])
            reconciliations.append(
                Reconciliation(
                    fund_name=name,
                    closing_units=closing,
                    net_supported_movement=movement,
                    implied_prior_units=prior,
                    status="BLOCKED"
                    if blocked
                    else (
                        "SHARES_RECONCILED" if options.history_complete else "HISTORY_INCOMPLETE"
                    ),
                )
            )
        total = sum((h.reported_value for h in parsed.holdings), Decimal(0))
    token = sha256(
        (parsed.model_dump_json() + options.model_dump_json() + state.model_dump_json()).encode()
    ).hexdigest()
    return RetirementPreview(
        portfolio_id=state.portfolio_id,
        preview_token=token,
        options=options,
        source=parsed,
        funds=tuple(funds),
        reported_total=total,
        issues=tuple(issues),
        reconciliation=tuple(reconciliations),
        can_commit=not any(i.blocking for i in issues),
    )
