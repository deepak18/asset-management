import type {
  HoldingAnalytics,
  HoldingInfo,
  PortfolioAnalytics,
  PortfolioSummary,
  Transaction,
} from "@/types/domain";

/**
 * Deterministic fixtures shaped by the generated contract types.
 *
 * Because these are typed as the real domain models, a breaking change to
 * `backend/openapi.json` (regenerated into `types/api.ts`) surfaces here as a
 * compile error — the mocks can never silently drift from the contract. Money
 * values are Decimal STRINGS, exactly as the backend serializes them.
 *
 * Portfolio 1 is the fully-priced happy path; portfolio 2 exercises the
 * "unpriced / null" degradation (no market values, empty allocations); portfolio
 * 3 is freshly imported, so most holdings are UNCLASSIFIED and drive the
 * classification flows; portfolio 99 is the empty ledger. Portfolio 404 is
 * intentionally absent (see handlers).
 */

export const portfolioSummary: PortfolioSummary = {
  id: 1,
  name: "Growth Portfolio",
  base_currency: "USD",
};

export const transactions: Transaction[] = [
  {
    ticker: "AAPL",
    type: "BUY",
    trade_date: "2024-01-15",
    currency: "USD",
    quantity: "10",
    price: "185.50",
    fees: "1.00",
    amount: "0",
    split_ratio: "1",
    sector: "Technology",
    industry: "Consumer Electronics",
  },
  {
    ticker: "MSFT",
    type: "BUY",
    trade_date: "2024-02-01",
    currency: "USD",
    quantity: "5",
    price: "410.00",
    fees: "1.00",
    amount: "0",
    split_ratio: "1",
    sector: "Technology",
    industry: "Software—Infrastructure",
  },
  {
    ticker: "AAPL",
    type: "DIVIDEND",
    trade_date: "2024-03-10",
    currency: "USD",
    quantity: "0",
    price: "0",
    fees: "0",
    amount: "2.40",
    split_ratio: "1",
    sector: "Technology",
    industry: "Consumer Electronics",
  },
  {
    ticker: "AAPL",
    type: "SELL",
    trade_date: "2024-06-20",
    currency: "USD",
    quantity: "4",
    price: "210.00",
    fees: "1.00",
    amount: "0",
    split_ratio: "1",
    sector: "Technology",
    industry: "Consumer Electronics",
  },
];

export const holdings: HoldingInfo[] = [
  {
    ticker: "AAPL",
    sector: "Technology",
    industry: "Consumer Electronics",
    classification_source: "MANUAL",
    data_gaps: [],
  },
  {
    ticker: "MSFT",
    sector: "Technology",
    industry: "Software—Infrastructure",
    classification_source: "PROVIDER",
    data_gaps: [],
  },
  {
    ticker: "XYZ",
    sector: null,
    industry: null,
    classification_source: "NONE",
    data_gaps: ["SECTOR", "INDUSTRY"],
  },
];

/** Fully-priced analytics: market values present, allocations populated. */
export const analyticsPriced: PortfolioAnalytics = {
  portfolio: portfolioSummary,
  base_currency: "USD",
  positions: [
    {
      ticker: "AAPL",
      open_quantity: "6",
      classification_source: "MANUAL",
      data_gaps: [],
      open_cost_basis_base: "1113.60",
      realized_pnl_base: "97.60",
      dividends_base: "2.40",
      fees_base: "3.00",
      open_lots: [
        { trade_date: "2024-01-15", quantity: "6", cost_per_share_base: "185.60" },
      ],
    },
    {
      ticker: "MSFT",
      open_quantity: "5",
      classification_source: "PROVIDER",
      data_gaps: [],
      open_cost_basis_base: "2050.00",
      realized_pnl_base: "0",
      dividends_base: "0",
      fees_base: "1.00",
      open_lots: [
        { trade_date: "2024-02-01", quantity: "5", cost_per_share_base: "410.00" },
      ],
    },
  ],
  realized_pnl_base: "97.60",
  dividends_base: "2.40",
  fees_base: "4.00",
  open_cost_basis_base: "3163.60",
  money_weighted_return: "0.1842",
  money_weighted_return_status: "OK",
  positions_unrealized: [
    {
      ticker: "AAPL",
      open_quantity: "6",
      open_cost_basis_base: "1113.60",
      market_value_base: "1290.00",
      unrealized_pnl_base: "176.40",
    },
    {
      ticker: "MSFT",
      open_quantity: "5",
      open_cost_basis_base: "2050.00",
      market_value_base: "2125.00",
      unrealized_pnl_base: "75.00",
    },
  ],
  market_value_base: "3415.00",
  unrealized_pnl_base: "251.40",
  allocation_by_ticker: [
    { key: "MSFT", market_value: "2125.00", weight: "0.6222" },
    { key: "AAPL", market_value: "1290.00", weight: "0.3778" },
  ],
  allocation_by_sector: [{ key: "Technology", market_value: "3415.00", weight: "1" }],
  allocation_by_industry: [
    { key: "Software—Infrastructure", market_value: "2125.00", weight: "0.6222" },
    { key: "Consumer Electronics", market_value: "1290.00", weight: "0.3778" },
  ],
  unpriced_tickers: [],
  priced_as_of: "2026-07-24T20:00:00Z",
};

/** Unpriced analytics: no market data, so market-value fields degrade to null. */
export const analyticsUnpriced: PortfolioAnalytics = {
  portfolio: { id: 2, name: "Unpriced Portfolio", base_currency: "USD" },
  base_currency: "USD",
  positions: analyticsPriced.positions,
  realized_pnl_base: "97.60",
  dividends_base: "2.40",
  fees_base: "4.00",
  open_cost_basis_base: "3163.60",
  money_weighted_return: null,
  // XIRR needs today's value of the open positions as its terminal cash flow;
  // without prices there is no root to solve for, so the reason is "unpriced".
  money_weighted_return_status: "UNPRICED_POSITIONS",
  positions_unrealized: [],
  market_value_base: null,
  unrealized_pnl_base: null,
  allocation_by_ticker: [],
  allocation_by_sector: [],
  allocation_by_industry: [],
  unpriced_tickers: ["AAPL", "MSFT"],
  priced_as_of: null,
};

/**
 * Freshly-imported analytics: priced, but a broker statement carries no sector
 * or industry, so most of the book lands in the `UNCLASSIFIED` bucket. This is
 * the fixture that drives the classify action and the inline editor.
 *
 * Sector/industry allocations are derived from these per-ticker rows at request
 * time (see `mocks/state.ts`), so classifying a holding visibly shrinks the
 * UNCLASSIFIED slice in dev mock mode.
 */
export const analyticsUnclassified: PortfolioAnalytics = {
  portfolio: { id: 3, name: "Imported Portfolio", base_currency: "USD" },
  base_currency: "USD",
  positions: ["NVDA", "PLTR", "SOFI", "ZZZZ"].map((ticker) => ({
    ticker,
    open_quantity: "10",
    open_cost_basis_base: "2250.00",
    realized_pnl_base: "0",
    dividends_base: "0",
    fees_base: "0",
    open_lots: [
      { trade_date: "2026-09-30", quantity: "10", cost_per_share_base: "225.00" },
    ],
    classification_source: ticker === "NVDA" ? "PROVIDER" : "NONE",
    data_gaps: ticker === "NVDA" ? [] : ["SECTOR", "INDUSTRY"],
  })),
  realized_pnl_base: "0",
  dividends_base: "0",
  fees_base: "0",
  open_cost_basis_base: "9000.00",
  money_weighted_return: null,
  // Snapshot-style opening lots only: one dated flow is not enough for a rate.
  money_weighted_return_status: "INSUFFICIENT_FLOWS",
  positions_unrealized: [],
  market_value_base: "10000.00",
  unrealized_pnl_base: "1000.00",
  allocation_by_ticker: [
    { key: "NVDA", market_value: "4000.00", weight: "0.4000" },
    { key: "PLTR", market_value: "3000.00", weight: "0.3000" },
    { key: "SOFI", market_value: "2000.00", weight: "0.2000" },
    { key: "ZZZZ", market_value: "1000.00", weight: "0.1000" },
  ],
  allocation_by_sector: [],
  allocation_by_industry: [],
  unpriced_tickers: [],
  priced_as_of: "2026-09-30T20:00:00Z",
};

/** Empty ledger: nothing bought yet — every roll-up is zero/empty. */
export const analyticsEmpty: PortfolioAnalytics = {
  portfolio: { id: 99, name: "Empty Portfolio", base_currency: "USD" },
  base_currency: "USD",
  positions: [],
  realized_pnl_base: "0",
  dividends_base: "0",
  fees_base: "0",
  open_cost_basis_base: "0",
  money_weighted_return: null,
  // No ledger at all — the fix is more history, not market data.
  money_weighted_return_status: "INSUFFICIENT_FLOWS",
  positions_unrealized: [],
  market_value_base: null,
  unrealized_pnl_base: null,
  allocation_by_ticker: [],
  allocation_by_sector: [],
  allocation_by_industry: [],
  unpriced_tickers: [],
  priced_as_of: null,
};

/**
 * Stand-in for the market-data provider's company profiles, used by the mock
 * classify endpoint. `ZZZZ` is deliberately absent so the "unresolved" branch
 * (provider returned nothing usable) is exercised too.
 */
export const profileDirectory: Record<string, { sector: string; industry: string }> = {
  AAPL: { sector: "Technology", industry: "Consumer Electronics" },
  MSFT: { sector: "Technology", industry: "Software—Infrastructure" },
  NVDA: { sector: "Technology", industry: "Semiconductors" },
  PLTR: { sector: "Technology", industry: "Software—Infrastructure" },
  SOFI: { sector: "Financial Services", industry: "Credit Services" },
  XYZ: { sector: "Industrials", industry: "Conglomerates" },
};

/** Per-portfolio holdings seed (mutated by classify / PATCH in mock state). */
export const holdingsById: Record<number, HoldingInfo[]> = {
  1: holdings,
  2: holdings.slice(0, 2),
  3: [
    {
      ticker: "NVDA",
      sector: "Technology",
      industry: "Semiconductors",
      classification_source: "PROVIDER",
      data_gaps: [],
    },
    {
      ticker: "PLTR",
      sector: null,
      industry: null,
      classification_source: "NONE",
      data_gaps: ["SECTOR", "INDUSTRY"],
    },
    {
      ticker: "SOFI",
      sector: null,
      industry: null,
      classification_source: "NONE",
      data_gaps: ["SECTOR", "INDUSTRY"],
    },
    {
      ticker: "ZZZZ",
      sector: null,
      industry: null,
      classification_source: "NONE",
      data_gaps: ["SECTOR", "INDUSTRY"],
    },
  ],
};

/** Lookup table used by the handlers to serve per-id analytics scenarios. */
export const analyticsById: Record<number, PortfolioAnalytics> = {
  1: analyticsPriced,
  2: analyticsUnpriced,
  3: analyticsUnclassified,
  99: analyticsEmpty,
};

export const summariesById: Record<number, PortfolioSummary> = {
  1: portfolioSummary,
  2: analyticsUnpriced.portfolio,
  3: analyticsUnclassified.portfolio,
  99: analyticsEmpty.portfolio,
};

/**
 * Per-holding money-weighted return (XIRR) fixtures, keyed `"{portfolioId}:{TICKER}"`.
 *
 * Each holding is scored on its *own* dated cash flows, so a holding's status is
 * independent of other holdings' missing prices/FX — the keys below deliberately
 * mix statuses *within* a portfolio to prove that:
 *
 *   * `1:AAPL` → OK positive, valued from a live QUOTE (provenance attached);
 *   * `1:MSFT` → OK negative, valued from a live QUOTE;
 *   * `1:XYZ`  → MISSING_FX — a foreign-currency holding in the *same* priced
 *     portfolio, withheld without suppressing AAPL/MSFT;
 *   * `2:AAPL` → UNPRICED_POSITION in an unpriced portfolio (no terminal value);
 *   * `2:MSFT` → OK zero from the LEDGER — a *closed* position needs no quote, so
 *     it still reports a return even though the portfolio is otherwise unpriced;
 *   * `3:NVDA`/`3:ZZZZ` → INCOMPLETE_HISTORY (snapshot / unconfirmed import);
 *   * `3:PLTR` → INSUFFICIENT_FLOWS (a single dated flow has no rate);
 *   * `3:SOFI` → INVALID_HISTORY (flows cannot produce a valid return).
 *
 * Unavailable returns are `null` with `valuation_source: "UNAVAILABLE"` and no
 * provenance — never a synthetic zero and never invented metadata.
 */
export const holdingAnalyticsByKey: Record<string, HoldingAnalytics> = {
  "1:AAPL": {
    portfolio_id: 1,
    ticker: "AAPL",
    base_currency: "USD",
    money_weighted_return: "0.1842",
    money_weighted_return_status: "OK",
    valuation_date: "2026-07-24",
    valuation_source: "QUOTE",
    valuation_provenance: {
      provider_code: "ALPHAVANTAGE",
      source_table: "GLOBAL_QUOTE",
      as_of: "2026-07-24T20:00:00Z",
    },
  },
  "1:MSFT": {
    portfolio_id: 1,
    ticker: "MSFT",
    base_currency: "USD",
    money_weighted_return: "-0.0530",
    money_weighted_return_status: "OK",
    valuation_date: "2026-07-24",
    valuation_source: "QUOTE",
    valuation_provenance: {
      provider_code: "ALPHAVANTAGE",
      source_table: "GLOBAL_QUOTE",
      as_of: "2026-07-24T20:00:00Z",
    },
  },
  "1:XYZ": {
    portfolio_id: 1,
    ticker: "XYZ",
    base_currency: "USD",
    money_weighted_return: null,
    money_weighted_return_status: "MISSING_FX",
    valuation_date: "2026-07-24",
    valuation_source: "UNAVAILABLE",
    valuation_provenance: null,
  },
  "2:AAPL": {
    portfolio_id: 2,
    ticker: "AAPL",
    base_currency: "USD",
    money_weighted_return: null,
    money_weighted_return_status: "UNPRICED_POSITION",
    valuation_date: "2026-07-24",
    valuation_source: "UNAVAILABLE",
    valuation_provenance: null,
  },
  "2:MSFT": {
    portfolio_id: 2,
    ticker: "MSFT",
    base_currency: "USD",
    money_weighted_return: "0",
    money_weighted_return_status: "OK",
    valuation_date: "2026-04-01",
    valuation_source: "LEDGER",
    valuation_provenance: null,
  },
  "3:NVDA": {
    portfolio_id: 3,
    ticker: "NVDA",
    base_currency: "USD",
    money_weighted_return: null,
    money_weighted_return_status: "INCOMPLETE_HISTORY",
    valuation_date: "2026-09-30",
    valuation_source: "UNAVAILABLE",
    valuation_provenance: null,
  },
  "3:PLTR": {
    portfolio_id: 3,
    ticker: "PLTR",
    base_currency: "USD",
    money_weighted_return: null,
    money_weighted_return_status: "INSUFFICIENT_FLOWS",
    valuation_date: "2026-09-30",
    valuation_source: "UNAVAILABLE",
    valuation_provenance: null,
  },
  "3:SOFI": {
    portfolio_id: 3,
    ticker: "SOFI",
    base_currency: "USD",
    money_weighted_return: null,
    money_weighted_return_status: "INVALID_HISTORY",
    valuation_date: "2026-09-30",
    valuation_source: "UNAVAILABLE",
    valuation_provenance: null,
  },
  "3:ZZZZ": {
    portfolio_id: 3,
    ticker: "ZZZZ",
    base_currency: "USD",
    money_weighted_return: null,
    money_weighted_return_status: "INCOMPLETE_HISTORY",
    valuation_date: "2026-09-30",
    valuation_source: "UNAVAILABLE",
    valuation_provenance: null,
  },
};
