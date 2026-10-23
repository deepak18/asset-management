"""Entirely fictitious source exports; no private account data or tracked CSV files."""

from datetime import date

from app.portfolio.vanguard import ACTIVITY_HEADER, HOLDINGS_HEADER, ImportOptions, ImportState

OPTIONS = ImportOptions(as_of=date(2026, 1, 31), currency="USD")
STATE = ImportState(
    portfolio_id=1,
    base_currency="USD",
    external_account_id=None,
    custodian=None,
    account_type="UNKNOWN",
    securities=(),
    imports=(),
    valuations=(),
    event_fingerprints=(),
)


def export(
    *,
    units: str = "10.0000000001",
    amount: str = "20.01",
    code: str = "114001",
    fund: str = "Fictional Growth",
    trade: str = "01/03/2026",
    account: str = "000042",
    extra_activity: str = "",
    extra_holdings: str = "",
    quantity: str = "2",
) -> bytes:
    return (
        f"{HOLDINGS_HEADER}\n42,Fictional Plan,{fund},{units},10.003,100.05,\n"
        f"{extra_holdings}\n{ACTIVITY_HEADER}\n"
        f"{account},{trade},02/02/2026,{code},Plan Contribution,{fund},10.003,{quantity},{amount},\n"
        f"{extra_activity}"
    ).encode()
