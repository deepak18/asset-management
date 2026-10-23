import type {
  ActivityFact,
  RetirementOptions,
  RetirementPreview,
  ValuationView,
  SecurityInfo,
} from "@/types/domain";

/** Entirely fictitious. The mock accepts only these bytes, never parses arbitrary CSV. */
export const demoRetirementCsv =
  "Plan Number,Plan Name,Fund Name,Shares,Price,Total Value,\n000042,Fictional Example Plan,Example Balanced Trust,12.3456789012,20.01,247.05,\n\nAccount Number,Trade Date,Run Date,Transaction Activity,Transaction Description,Investment Name,Share Price,Transaction Shares,Dollar Amount,\n000042,10/01/2026,10/02/2026,114001,Plan Contribution,Example Balanced Trust,20.01,1.234,24.70,\n";
export const demoSecurity: SecurityInfo = {
  id: 701,
  name: "Example Balanced Trust",
  instrument_type: "UNKNOWN",
  ticker: null,
  currency: "USD",
  aliases: [],
};
const provenance = {
  checksum: "fictional-checksum",
  source_line: 5,
  source_reference: "fictional-checksum:5",
  raw_fields: [
    "000042",
    "10/01/2026",
    "10/02/2026",
    "114001",
    "Plan Contribution",
    "Example Balanced Trust",
    "20.01",
    "1.234",
    "24.70",
    "",
  ],
};
export const demoActivity: ActivityFact = {
  ...provenance,
  account_number: "000042",
  trade_date: "2026-10-01",
  run_date: "2026-10-02",
  code: "114001",
  description: "Plan Contribution",
  fund_name: demoSecurity.name,
  price: "20.01",
  quantity: "1.234",
  amount: "24.70",
  kind: "CONTRIBUTION",
  fingerprint: "fictional-event",
  external_contribution: "24.70",
  dividend_amount: null,
};

export function demoPreview(
  portfolioId: number,
  options: RetirementOptions,
  token = "fictional-review",
): RetirementPreview {
  return {
    portfolio_id: portfolioId,
    preview_token: token,
    options,
    source: {
      checksum: "fictional-checksum",
      plan_number: "000042",
      plan_name: "Fictional Example Plan",
      account_number: "000042",
      holdings: [
        {
          checksum: "fictional-checksum",
          source_line: 2,
          source_reference: "fictional-checksum:2",
          raw_fields: [
            "000042",
            "Fictional Example Plan",
            demoSecurity.name,
            "12.3456789012",
            "20.01",
            "247.05",
            "",
          ],
          plan_number: "000042",
          plan_name: "Fictional Example Plan",
          fund_name: demoSecurity.name,
          quantity: "12.3456789012",
          reported_price: "20.01",
          reported_value: "247.05",
          cost_basis: null,
          unrealized_pnl: null,
        },
      ],
      activity: [demoActivity],
    },
    funds: [
      {
        fund_name: demoSecurity.name,
        alias_value: "fictional-plan:example-balanced",
        security_id: null,
        ticker: null,
        status: "WILL_CREATE_UNKNOWN",
      },
    ],
    reported_total: "247.05",
    cost_basis: null,
    unrealized_pnl: null,
    money_weighted_return: null,
    issues: options.history_complete
      ? [
          {
            code: "COMPLETE_HISTORY_MISMATCH",
            blocking: true,
            message: "The fictitious export does not reconcile as inception history.",
          },
        ]
      : [
          {
            code: "INCOMPLETE_HISTORY",
            blocking: false,
            message: "The fictitious export covers only a partial period.",
          },
        ],
    reconciliation: [
      {
        fund_name: demoSecurity.name,
        closing_units: "12.3456789012",
        net_supported_movement: "1.234",
        implied_prior_units: "11.1116789012",
        status: options.history_complete ? "BLOCKED" : "HISTORY_INCOMPLETE",
        performance_calculable: false,
      },
    ],
    can_commit: !options.history_complete,
  };
}

export function demoValuation(portfolioId: number, asOf: string): ValuationView {
  const provenance = {
    source_code: "VANGUARD",
    source_reference: "fictional-checksum",
    as_of: asOf,
    imported_at: "2026-10-22T12:00:00Z",
  };
  return {
    portfolio_id: portfolioId,
    view: "REPORTED_SNAPSHOT",
    status: "AVAILABLE",
    snapshot: {
      id: 801,
      portfolio_id: portfolioId,
      as_of: asOf,
      currency: "USD",
      complete_snapshot: true,
      positions: [
        {
          security_id: 701,
          quantity: "12.3456789012",
          reported_price: "20.01",
          reported_value: "247.05",
          cost_basis: null,
          unrealized_pnl: null,
          money_weighted_return: null,
          history_status: "VALUATION_ONLY",
          provenance,
        },
      ],
      reported_total: "247.05",
      cost_basis: null,
      unrealized_pnl: null,
      money_weighted_return: null,
      history_status: "VALUATION_ONLY",
      provenance,
    },
  };
}
