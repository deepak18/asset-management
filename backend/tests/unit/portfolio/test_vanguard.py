"""Pure parser/policy plus mocked provider and storage boundary coverage."""

from datetime import date
from decimal import Decimal, localcontext
from typing import cast
from unittest.mock import AsyncMock

import pytest

from app.portfolio.accounts import (
    AccountConflict,
    AccountValidationError,
    SecurityAlias,
    SecurityInfo,
)
from app.portfolio.vanguard import (
    ACTIVITY_HEADER,
    HOLDINGS_HEADER,
    ActivityKind,
    IssueCode,
    build_preview,
    fund_alias,
    normalized_account,
    parse_vanguard,
)
from app.portfolio.vanguard_service import (
    MAX_UPLOAD_BYTES,
    RetirementUploadTooLarge,
    VanguardService,
)
from app.providers.retirement_import_provider import RetirementImportProvider
from app.providers.statement_storage import StatementStorage, StatementStorageError
from tests.vanguard_fixtures import OPTIONS, STATE, export


def test_bom_quoted_names_trailing_commas_blank_lines_and_independent_facts() -> None:
    data = b"\xef\xbb\xbf" + export(fund='"Fictional, Growth"').replace(b",\n", b",,,\r\n")
    parsed = parse_vanguard(data)
    assert parsed.account_number == "000042" and parsed.plan_number == "42"
    assert parsed.holdings[0].fund_name == "Fictional, Growth"
    assert parsed.holdings[0].quantity == Decimal("10.0000000001")
    assert parsed.activity[0].amount == Decimal("20.01")
    assert parsed.activity[0].price * parsed.activity[0].quantity != parsed.activity[0].amount
    assert parsed.activity[0].source_line == 5
    assert parsed.activity[0].raw_fields[0] == "000042"
    assert parsed.checksum in parsed.activity[0].source_reference
    preview = build_preview(parsed, OPTIONS, STATE)
    assert preview.reported_total == Decimal("100.05")  # not current value + activity
    assert preview.cost_basis is preview.unrealized_pnl is preview.money_weighted_return is None
    assert preview.options.as_of == date(2026, 1, 31)  # not February run date
    assert preview.can_commit
    assert preview.funds[0].ticker is None and preview.funds[0].security_id is None
    assert preview.reconciliation[0].implied_prior_units == Decimal("8.0000000001")
    assert not preview.reconciliation[0].performance_calculable


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\xff",
        HOLDINGS_HEADER.encode(),
        ACTIVITY_HEADER.encode(),
        export().replace(
            HOLDINGS_HEADER.encode(), b"Plan Number,Fund Name,Shares,Price,Total Value,"
        ),
        export().replace(ACTIVITY_HEADER.encode(), b"Account Number,Trade Date,broken,"),
        export() + (ACTIVITY_HEADER + "\n").encode(),
        export() + (HOLDINGS_HEADER + "\n").encode(),
        export().replace(ACTIVITY_HEADER.encode(), b""),
        export().replace(b"Plan Number", b"plan number"),
        export().replace(b"Fictional Plan", b""),
        export().replace(b"Plan Contribution", b""),
        export().replace(b"Fictional Growth", b""),
        export().replace(b"42,Fictional Plan", b"not-account,Fictional Plan"),
        export() + b'"unterminated',
        (ACTIVITY_HEADER + "\n" + HOLDINGS_HEADER).encode(),
    ],
)
def test_malformed_csv(content: bytes) -> None:
    with pytest.raises(AccountValidationError):
        parse_vanguard(content)


@pytest.mark.parametrize(
    "number",
    [
        "NaN",
        "Infinity",
        "-Infinity",
        "nan",
        "1e4",
        "1,000",
        "",
        " 1",
        "0.00000000001",
        "12345678901234567890123456789",
        "-1",
    ],
)
def test_invalid_holding_numbers(number: str) -> None:
    with pytest.raises(AccountValidationError):
        parse_vanguard(export(units=number))


@pytest.mark.parametrize("trade", ["2026-01-03", "1/03/2026", "02/30/2026", "03/01/2026"])
def test_invalid_or_inconsistent_dates(trade: str) -> None:
    with pytest.raises(AccountValidationError):
        parse_vanguard(export(trade=trade))


def test_plan_account_and_duplicate_holding_validation() -> None:
    with pytest.raises(AccountConflict, match="do not match"):
        parse_vanguard(export(account="0043"))
    with pytest.raises(AccountValidationError, match="exactly one"):
        parse_vanguard(export(extra_holdings="43,Other Plan,Other Fund,1,1,1,\n"))
    with pytest.raises(AccountValidationError, match="duplicate holding"):
        parse_vanguard(export(extra_holdings="42,Fictional Plan,Fictional Growth,1,1,1,\n"))
    with pytest.raises(AccountValidationError, match="exactly one"):
        parse_vanguard(
            export(extra_activity="43,01/03/2026,02/02/2026,114001,Contribution,Other,1,1,1,\n")
        )


def test_identical_rows_preserve_multiplicity_but_canonical_fingerprints_ignore_decimal_scale() -> (
    None
):
    row = "42,01/03/2026,02/02/2026,114001,Plan Contribution,Fictional Growth,10.0030,2.0,20.010,\n"
    parsed = parse_vanguard(export(extra_activity=row))
    assert len(parsed.activity) == 2
    assert parsed.activity[0].fingerprint == parsed.activity[1].fingerprint
    preview = build_preview(parsed, OPTIONS, STATE)
    assert preview.reconciliation[0].net_supported_movement == 4
    assert parsed.activity[0].source_line != parsed.activity[1].source_line


def test_sample_shape_twelve_holdings_twenty_four_activities_without_assuming_each_fund_transacted() -> (
    None
):
    holdings = "".join(f"42,Fictional Plan,Fund {n},100,1,100,\n" for n in range(1, 12))
    events = "".join(
        f"000042,01/{n + 1:02}/2026,02/02/2026,{'114001' if n < 22 else '219004'},"
        f"{'Plan Contribution' if n < 22 else 'Dividends on Equity Investments'},"
        f"Fund {n % 10 + 1},1,1,1,\n"
        for n in range(1, 24)
    )
    parsed = parse_vanguard(export(units="100", extra_holdings=holdings, extra_activity=events))
    assert len(parsed.holdings) == 12 and len(parsed.activity) == 24
    assert sum(a.kind == ActivityKind.CONTRIBUTION for a in parsed.activity) == 22
    assert sum(a.kind == ActivityKind.REINVESTMENT for a in parsed.activity) == 2
    preview = build_preview(parsed, OPTIONS, STATE)
    assert len(preview.funds) == 12
    no_activity = next(r for r in preview.reconciliation if r.fund_name == "Fund 11")
    assert no_activity.net_supported_movement == 0 and no_activity.implied_prior_units == 100


def test_reinvestment_retains_dividend_and_units_not_external_contribution() -> None:
    fact = parse_vanguard(export(code="219004")).activity[0]
    assert fact.kind == ActivityKind.REINVESTMENT
    assert fact.dividend_amount == Decimal("20.01") and fact.quantity == 2
    assert fact.external_contribution is None


@pytest.mark.parametrize(
    "code,quantity,issue",
    [
        ("998877", "-2", IssueCode.UNSUPPORTED_ACTIVITY),
        ("114001", "-2", IssueCode.INVALID_MOVEMENT),
        ("219004", "0", IssueCode.INVALID_MOVEMENT),
        ("114001", "12", IssueCode.NEGATIVE_PRIOR_BALANCE),
    ],
)
def test_blocking_movements(code: str, quantity: str, issue: IssueCode) -> None:
    parsed = parse_vanguard(export(code=code, quantity=quantity))
    preview = build_preview(parsed, OPTIONS, STATE)
    assert not preview.can_commit and any(i.code == issue and i.blocking for i in preview.issues)
    if code == "998877":
        assert preview.reconciliation[0].net_supported_movement is None
        assert preview.reconciliation[0].implied_prior_units is None
        assert preview.source.activity[0].quantity == -2


def test_closed_activity_only_fund_is_visible_and_not_silently_zeroed() -> None:
    parsed = parse_vanguard(
        export(
            extra_activity="000042,01/01/2026,02/02/2026,999,Closed fund sale,Closed Fund,2,-3,6,\n"
        )
    )
    preview = build_preview(parsed, OPTIONS, STATE)
    assert len(preview.funds) == 2
    closed = next(r for r in preview.reconciliation if r.fund_name == "Closed Fund")
    assert closed.closing_units == 0 and closed.net_supported_movement is None
    assert not preview.can_commit


def test_complete_history_requires_supported_exact_share_reconciliation_not_return_calculability() -> (
    None
):
    complete = OPTIONS.model_copy(update={"history_complete": True})
    assert not build_preview(parse_vanguard(export()), complete, STATE).can_commit
    preview = build_preview(parse_vanguard(export(units="2")), complete, STATE)
    assert preview.can_commit and preview.reconciliation[0].status == "SHARES_RECONCILED"
    assert preview.money_weighted_return is None
    unsupported = build_preview(parse_vanguard(export(units="2", code="99")), complete, STATE)
    assert not unsupported.can_commit


def test_future_trade_blocked_without_asof_inference() -> None:
    preview = build_preview(parse_vanguard(export(trade="02/01/2026")), OPTIONS, STATE)
    assert not preview.can_commit and any(i.code == IssueCode.FUTURE_TRADE for i in preview.issues)


@pytest.mark.parametrize("raw,normalized", [("000042", "42"), ("42", "42"), ("000", "0")])
def test_normalization_and_account_binding(raw: str, normalized: str) -> None:
    assert normalized_account(raw) == normalized
    parsed = parse_vanguard(export())
    if normalized == "42":
        assert build_preview(
            parsed, OPTIONS, STATE.model_copy(update={"external_account_id": raw})
        ).can_commit
    else:
        with pytest.raises(AccountConflict, match="bound"):
            build_preview(parsed, OPTIONS, STATE.model_copy(update={"external_account_id": raw}))


def test_mappings_are_scoped_to_exact_fund_plan_and_account() -> None:
    alias = fund_alias("42", "000042", "Fictional Growth")
    assert alias == fund_alias("00042", "42", "Fictional Growth")
    assert alias != fund_alias("43", "43", "Fictional Growth")
    assert alias != fund_alias("42", "42", "Fictional Growth ")
    security = SecurityInfo(
        id=9,
        name="Explicit Class",
        currency="USD",
        ticker="FAKE",
        aliases=(SecurityAlias(source_code="VANGUARD", value=alias),),
    )
    state = STATE.model_copy(update={"securities": (security,)})
    preview = build_preview(parse_vanguard(export()), OPTIONS, state)
    assert preview.funds[0].security_id == 9 and preview.funds[0].ticker == "FAKE"
    with pytest.raises(AccountConflict, match="mapping"):
        build_preview(
            parse_vanguard(export()),
            OPTIONS,
            state.model_copy(
                update={
                    "securities": (security.model_copy(update={"currency": "INR"}),),
                }
            ),
        )


def test_duplicate_and_overlap_policy() -> None:
    parsed = parse_vanguard(export())
    with pytest.raises(AccountConflict, match="duplicate checksum"):
        build_preview(parsed, OPTIONS, STATE.model_copy(update={"imports": (parsed.checksum,)}))
    with pytest.raises(AccountConflict, match="nonoverlapping"):
        build_preview(
            parsed,
            OPTIONS,
            STATE.model_copy(update={"event_fingerprints": (parsed.activity[0].fingerprint,)}),
        )


@pytest.mark.parametrize("currency", ["EUR", "INR"])
def test_no_implicit_currency_conversion(currency: str) -> None:
    with pytest.raises(AccountValidationError):
        build_preview(
            parse_vanguard(export()), OPTIONS.model_copy(update={"currency": currency}), STATE
        )


def test_review_hash_covers_options_content_and_relevant_state() -> None:
    parsed = parse_vanguard(export())
    token = build_preview(parsed, OPTIONS, STATE).preview_token
    assert build_preview(parsed, OPTIONS, STATE).preview_token == token
    for options in (
        OPTIONS.model_copy(update={"as_of": date(2026, 2, 1)}),
        OPTIONS.model_copy(update={"history_complete": True}),
    ):
        assert build_preview(parsed, options, STATE).preview_token != token
    for state in (
        STATE.model_copy(update={"custodian": "Vanguard"}),
        STATE.model_copy(update={"account_type": "ROTH_401K"}),
        STATE.model_copy(update={"external_account_id": "42"}),
        STATE.model_copy(update={"valuations": ("changed",)}),
        STATE.model_copy(update={"imports": ("other",)}),
    ):
        assert build_preview(parsed, OPTIONS, state).preview_token != token
    assert (
        build_preview(parse_vanguard(export(amount="20.02")), OPTIONS, STATE).preview_token != token
    )


def test_exact_total_and_movement_are_independent_of_decimal_context() -> None:
    parsed = parse_vanguard(export())
    with localcontext() as context:
        context.prec = 3
        preview = build_preview(parsed, OPTIONS, STATE)
    assert preview.reported_total == Decimal("100.05")
    assert preview.reconciliation[0].implied_prior_units == Decimal("8.0000000001")


def test_row_and_field_size_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.portfolio.vanguard.MAX_ROWS", 3)
    with pytest.raises(AccountValidationError, match="exceeds"):
        parse_vanguard(export())
    with pytest.raises(AccountValidationError):
        parse_vanguard(export(fund="x" * 150000))


async def test_storage_readback_reparse_and_corrupt_bytes_fail_before_database_commit() -> None:
    provider = AsyncMock(spec=RetirementImportProvider)
    storage = AsyncMock(spec=StatementStorage)
    content = export()
    preview = build_preview(parse_vanguard(content), OPTIONS, STATE)
    provider.preview.return_value = preview
    storage.get.return_value = content
    service = VanguardService(
        cast(RetirementImportProvider, provider),
        cast(StatementStorage, storage),
    )
    await service.preview(1, content, OPTIONS)
    storage.put.assert_not_called()
    await service.commit(1, content, OPTIONS, preview.preview_token)
    storage.put.assert_awaited_once_with(f"vanguard-{preview.source.checksum}.csv", content)
    provider.commit.assert_awaited_once()
    assert provider.commit.call_args.args[1] == parse_vanguard(content)
    provider.commit.reset_mock()
    storage.get.return_value = b"corrupt"
    with pytest.raises(AccountValidationError, match="checksum"):
        await service.commit(1, content, OPTIONS, preview.preview_token)
    provider.commit.assert_not_called()
    storage.get.side_effect = StatementStorageError("offline")
    with pytest.raises(AccountValidationError, match="storage"):
        await service.commit(1, content, OPTIONS, preview.preview_token)
    with pytest.raises(AccountConflict, match="stale"):
        await service.commit(1, content, OPTIONS, "changed")
    with pytest.raises(RetirementUploadTooLarge):
        await service.preview(1, b"x" * (MAX_UPLOAD_BYTES + 1), OPTIONS)


def test_multiline_quoted_fund_names_keep_starting_source_lines() -> None:
    parsed = parse_vanguard(export(fund='"Fictional,\nGrowth"'))
    assert parsed.holdings[0].fund_name == "Fictional,\nGrowth"
    assert parsed.holdings[0].source_line == 2
    assert parsed.activity[0].source_line == 6


def test_genuine_nonnumeric_bound_account_is_a_conflict() -> None:
    with pytest.raises(AccountConflict, match="bound"):
        build_preview(
            parse_vanguard(export()),
            OPTIONS,
            STATE.model_copy(update={"external_account_id": "Other-Account"}),
        )


def test_two_funds_mapped_to_one_security_are_not_conflated() -> None:
    aliases = tuple(
        SecurityAlias(source_code="VANGUARD", value=fund_alias("42", "42", name))
        for name in ("Fictional Growth", "Other Fund")
    )
    security = SecurityInfo(id=7, name="Manual", currency="USD", aliases=aliases)
    parsed = parse_vanguard(export(extra_holdings="42,Fictional Plan,Other Fund,2,10,20,\n"))
    with pytest.raises(AccountConflict, match="multiple source funds"):
        build_preview(parsed, OPTIONS, STATE.model_copy(update={"securities": (security,)}))


def test_negative_source_cash_is_retained_but_blocks_supported_activity() -> None:
    parsed = parse_vanguard(export(amount="-2.01"))
    assert parsed.activity[0].amount == Decimal("-2.01")
    preview = build_preview(parsed, OPTIONS, STATE)
    assert not preview.can_commit and any(
        i.code == IssueCode.INVALID_MOVEMENT for i in preview.issues
    )
