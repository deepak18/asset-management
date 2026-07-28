import type {
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
 * 99 is the empty ledger. Portfolio 404 is intentionally absent (see handlers).
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
  { ticker: "AAPL", sector: "Technology", industry: "Consumer Electronics" },
  { ticker: "MSFT", sector: "Technology", industry: "Software—Infrastructure" },
  { ticker: "XYZ", sector: null, industry: null },
];

/** Fully-priced analytics: market values present, allocations populated. */
export const analyticsPriced: PortfolioAnalytics = {
  portfolio: portfolioSummary,
  base_currency: "USD",
  positions: [
    {
      ticker: "AAPL",
      open_quantity: "6",
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
  allocation_by_sector: [
    { key: "Technology", market_value: "3415.00", weight: "1" },
  ],
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
  positions_unrealized: [],
  market_value_base: null,
  unrealized_pnl_base: null,
  allocation_by_ticker: [],
  allocation_by_sector: [],
  allocation_by_industry: [],
  unpriced_tickers: ["AAPL", "MSFT"],
  priced_as_of: null,
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
  positions_unrealized: [],
  market_value_base: null,
  unrealized_pnl_base: null,
  allocation_by_ticker: [],
  allocation_by_sector: [],
  allocation_by_industry: [],
  unpriced_tickers: [],
  priced_as_of: null,
};

/** Lookup table used by the handlers to serve per-id analytics scenarios. */
export const analyticsById: Record<number, PortfolioAnalytics> = {
  1: analyticsPriced,
  2: analyticsUnpriced,
  99: analyticsEmpty,
};

export const summariesById: Record<number, PortfolioSummary> = {
  1: portfolioSummary,
  2: analyticsUnpriced.portfolio,
  99: analyticsEmpty.portfolio,
};
