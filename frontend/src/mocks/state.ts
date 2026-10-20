import type {
  AllocationWeight,
  ClassificationFailure,
  HoldingAnalytics,
  HoldingClassificationResult,
  HoldingClassificationUpdate,
  HoldingInfo,
  LedgerIngestResult,
  PortfolioAnalytics,
  PortfolioCreate,
  PortfolioSummary,
  StatementImportStatus,
} from "@/types/domain";
import { UNCLASSIFIED_KEY } from "@/types/domain";
import {
  analyticsById,
  holdingsById,
  holdingAnalyticsByKey,
  profileDirectory,
  summariesById,
  transactions,
} from "@/mocks/fixtures";

/**
 * Mutable in-memory state backing the *write* MSW handlers.
 *
 * The read fixtures (portfolios 1/2/3/99) are static, but create/import/add and
 * classification flows need somewhere to record their effect so the UI can
 * observe it — a picker that shows a just-created portfolio, an import job that
 * visibly progresses across polls, an UNCLASSIFIED allocation slice that shrinks
 * once holdings are classified. `resetMockState()` restores the seed so Vitest
 * tests stay isolated (called from vitest.setup.ts `afterEach`).
 */

interface JobRuntime {
  job: StatementImportStatus;
  /** How many times this job has been polled — drives the fake progression. */
  polls: number;
}

interface State {
  portfolios: PortfolioSummary[];
  nextPortfolioId: number;
  holdings: Map<number, HoldingInfo[]>;
  jobsByPortfolio: Map<number, JobRuntime[]>;
  nextJobId: number;
  /** When false the classify endpoint answers 503 (no provider configured). */
  marketDataConfigured: boolean;
}

function seed(): State {
  return {
    portfolios: [
      summariesById[1]!,
      summariesById[2]!,
      summariesById[3]!,
      summariesById[99]!,
    ].filter(Boolean),
    nextPortfolioId: 100,
    // Deep-copy: classify/PATCH mutate these, and fixtures must stay pristine
    // across tests.
    holdings: new Map(
      Object.entries(holdingsById).map(([id, rows]) => [
        Number(id),
        rows.map((row) => ({ ...row, data_gaps: [...row.data_gaps] })),
      ]),
    ),
    jobsByPortfolio: new Map(),
    nextJobId: 1,
    marketDataConfigured: true,
  };
}

let state: State = seed();

export function resetMockState(): void {
  state = seed();
}

/** Toggle the mock market-data provider off to demo the classify 503 branch. */
export function setMarketDataConfigured(configured: boolean): void {
  state.marketDataConfigured = configured;
}

export function listPortfolios(): PortfolioSummary[] {
  return state.portfolios;
}

export function findPortfolio(id: number): PortfolioSummary | undefined {
  return state.portfolios.find((p) => p.id === id);
}

export function createPortfolio(body: PortfolioCreate): PortfolioSummary {
  const summary: PortfolioSummary = {
    id: state.nextPortfolioId++,
    name: body.name,
    base_currency: body.base_currency,
  };
  state.portfolios = [...state.portfolios, summary];
  return summary;
}

/** Empty analytics envelope for a portfolio with no seeded ledger. */
function emptyAnalytics(summary: PortfolioSummary): PortfolioAnalytics {
  return {
    portfolio: summary,
    base_currency: summary.base_currency,
    positions: [],
    realized_pnl_base: "0",
    dividends_base: "0",
    fees_base: "0",
    open_cost_basis_base: "0",
    money_weighted_return: null,
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
}

/**
 * Roll per-ticker allocation rows up into sector/industry buckets using the
 * portfolio's *current* classification, so classifying a holding is visible in
 * the donuts on the next refetch.
 *
 * NB: this is fixture arithmetic, not the app's money path — the UI still only
 * ever formats the Decimal strings produced here. Integer-cent math keeps the
 * output exact for the round fixture values.
 */
function groupAllocation(
  rows: AllocationWeight[],
  classify: (ticker: string) => string | null | undefined,
): AllocationWeight[] {
  const cents = new Map<string, number>();
  let totalCents = 0;
  for (const row of rows) {
    const key = classify(row.key) || UNCLASSIFIED_KEY;
    const value = Math.round(Number(row.market_value) * 100);
    cents.set(key, (cents.get(key) ?? 0) + value);
    totalCents += value;
  }
  return [...cents.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([key, value]) => ({
      key,
      market_value: (value / 100).toFixed(2),
      weight: totalCents === 0 ? "0" : (value / totalCents).toFixed(4),
    }));
}

export function getAnalytics(id: number): PortfolioAnalytics | undefined {
  const fixture = analyticsById[id];
  if (fixture) {
    const rows = state.holdings.get(id);
    if (!rows) {
      return fixture;
    }
    const byTicker = new Map(rows.map((h) => [h.ticker, h]));
    return {
      ...fixture,
      positions: fixture.positions.map((position) => ({
        ...position,
        classification_source:
          byTicker.get(position.ticker)?.classification_source ??
          position.classification_source,
        data_gaps: byTicker.get(position.ticker)?.data_gaps ?? position.data_gaps,
      })),
      allocation_by_sector: groupAllocation(
        fixture.allocation_by_ticker,
        (t) => byTicker.get(t)?.sector,
      ),
      allocation_by_industry: groupAllocation(
        fixture.allocation_by_ticker,
        (t) => byTicker.get(t)?.industry,
      ),
    };
  }
  const summary = findPortfolio(id);
  return summary ? emptyAnalytics(summary) : undefined;
}

export function getTransactions(id: number) {
  if (!findPortfolio(id)) {
    return undefined;
  }
  return id === 1 ? transactions : [];
}

export function getHoldings(id: number): HoldingInfo[] | undefined {
  if (!findPortfolio(id)) {
    return undefined;
  }
  return state.holdings.get(id) ?? [];
}

/**
 * This holding's own money-weighted return (XIRR), scored on its *own* cash flows.
 *
 * Returns `undefined` (→ 404) when the portfolio is absent or the ticker is not
 * held, mirroring the backend. The per-holding fixture is looked up by
 * `"{id}:{TICKER}"`, so one holding's withheld return (missing FX, unpriced open
 * position) never suppresses another's — exactly the independence the contract
 * guarantees. A held ticker with no explicit fixture reports INCOMPLETE_HISTORY
 * (its history is unknown to the mock) rather than a fabricated figure.
 */
export function getHoldingAnalytics(
  id: number,
  ticker: string,
): HoldingAnalytics | undefined {
  const rows = getHoldings(id);
  if (!rows) {
    return undefined;
  }
  const symbol = ticker.toUpperCase();
  const holding = rows.find((h) => h.ticker.toUpperCase() === symbol);
  if (!holding) {
    return undefined;
  }
  const fixture = holdingAnalyticsByKey[`${id}:${symbol}`];
  if (fixture) {
    return fixture;
  }
  const summary = findPortfolio(id);
  return {
    portfolio_id: id,
    ticker: symbol,
    base_currency: summary?.base_currency ?? "USD",
    money_weighted_return: null,
    money_weighted_return_status: "INCOMPLETE_HISTORY",
    valuation_date: "2026-01-01",
    valuation_source: "UNAVAILABLE",
    valuation_provenance: null,
  };
}

/** Discriminated result of a classify attempt (503 = no provider configured). */
export type ClassifyAttempt =
  | { ok: true; result: HoldingClassificationResult }
  | { ok: false; status: 404 | 503; detail: string };

/**
 * Simulate the bounded backfill: classify at most `limit` holdings per call from
 * the stand-in profile directory, report what is left in `remaining` so the
 * caller loops, and split failures (`unresolved`) from no-ops (`skipped`).
 */
export function classifyHoldings(
  portfolioId: number,
  refresh: boolean,
  limit: number,
  afterTicker?: string,
): ClassifyAttempt {
  if (!findPortfolio(portfolioId)) {
    return { ok: false, status: 404, detail: "Portfolio not found" };
  }
  if (!state.marketDataConfigured) {
    return {
      ok: false,
      status: 503,
      detail:
        "No market-data provider is configured. Set ALPHAVANTAGE_API_KEY to enable classification.",
    };
  }

  const rows = state.holdings.get(portfolioId) ?? [];
  const needsWork = (h: HoldingInfo) =>
    refresh || (h.classification_source !== "MANUAL" && (!h.sector || !h.industry));
  const candidates = rows
    .filter((h) => needsWork(h) && (!afterTicker || h.ticker > afterTicker))
    .sort((a, b) => a.ticker.localeCompare(b.ticker));
  const skipped = rows.filter((h) => !needsWork(h)).map((h) => h.ticker);

  const batch = candidates.slice(0, limit);
  const classified: HoldingInfo[] = [];
  const unresolved: string[] = [];
  const failures: ClassificationFailure[] = [];
  for (const holding of batch) {
    const profile = profileDirectory[holding.ticker];
    if (!profile) {
      unresolved.push(holding.ticker);
      failures.push({ ticker: holding.ticker, reason: "NO_PROFILE" });
      continue;
    }
    holding.sector = profile.sector;
    holding.industry = profile.industry;
    holding.classification_source = "PROVIDER";
    holding.data_gaps = holding.data_gaps.filter(
      (gap) => gap !== "SECTOR" && gap !== "INDUSTRY",
    );
    classified.push({ ...holding });
  }

  return {
    ok: true,
    result: {
      portfolio_id: portfolioId,
      classified,
      unresolved,
      skipped,
      failures,
      next_cursor:
        candidates.length > batch.length ? (batch.at(-1)?.ticker ?? null) : null,
      // Unresolved tickers stay unclassified but were already attempted; only
      // the holdings the limit cut off count as remaining work.
      remaining: Math.max(candidates.length - batch.length, 0),
    },
  };
}

/** Manual override — independent of market data, 404 when not held. */
export function updateHoldingClassification(
  portfolioId: number,
  ticker: string,
  body: HoldingClassificationUpdate,
): HoldingInfo | undefined {
  const rows = state.holdings.get(portfolioId);
  const holding = rows?.find((h) => h.ticker.toUpperCase() === ticker.toUpperCase());
  if (!holding) {
    return undefined;
  }
  if ("sector" in body) {
    holding.sector = body.sector;
  }
  if ("industry" in body) {
    holding.industry = body.industry;
  }
  holding.classification_source = "MANUAL";
  holding.data_gaps = holding.data_gaps.filter(
    (gap) => gap !== "SECTOR" && gap !== "INDUSTRY",
  );
  if (!holding.sector) holding.data_gaps.push("SECTOR");
  if (!holding.industry) holding.data_gaps.push("INDUSTRY");
  return { ...holding };
}

export function ingest(
  id: number,
  tickers: string[],
  count: number,
): LedgerIngestResult {
  return {
    portfolio_id: id,
    created_transactions: count,
    tickers,
    warnings: [],
  };
}

/** Discriminated result of an import upload attempt. */
export type ImportUpload =
  | { ok: true; job: StatementImportStatus }
  | { ok: false; status: 409 | 413 | 422; detail: string };

/**
 * Simulate the upload endpoint. Filenames drive the demo error paths so the UI's
 * 409 / 413 / 422 branches can be exercised in dev and tests:
 *
 * * `*duplicate*` → 409 (unless `allowDuplicate`)
 * * `*large*`     → 413
 * * `*bad*`       → 422
 */
export function createImport(
  portfolioId: number,
  filename: string,
  sizeBytes: number,
  allowDuplicate: boolean,
): ImportUpload {
  const lower = filename.toLowerCase();
  if (lower.includes("large")) {
    return { ok: false, status: 413, detail: "File exceeds the 5 MB limit." };
  }
  if (lower.includes("bad")) {
    return {
      ok: false,
      status: 422,
      detail: "Not a recognizable Robinhood activity CSV.",
    };
  }
  if (lower.includes("duplicate") && !allowDuplicate) {
    return {
      ok: false,
      status: 409,
      detail:
        "This exact file was already imported. Importing again would double-count it.",
    };
  }

  const now = new Date().toISOString();
  const job: StatementImportStatus = {
    id: state.nextJobId++,
    portfolio_id: portfolioId,
    status: "PENDING",
    source_format: "robinhood_csv",
    original_filename: filename,
    checksum: `sha256:${filename}:${sizeBytes}`,
    size_bytes: sizeBytes,
    created_at: now,
    started_at: null,
    finished_at: null,
    total_rows: null,
    processed_rows: 0,
    created_transactions: 0,
    tickers: [],
    warnings: [],
    error: null,
    history_complete: false,
    retry_safe: true,
    unresolved_items: [],
  };
  const runtimes = state.jobsByPortfolio.get(portfolioId) ?? [];
  state.jobsByPortfolio.set(portfolioId, [{ job, polls: 0 }, ...runtimes]);
  return { ok: true, job };
}

/** Advance one job a step per poll: PENDING → RUNNING (counted) → SUCCEEDED. */
export function getImport(
  portfolioId: number,
  jobId: number,
): StatementImportStatus | undefined {
  const runtimes = state.jobsByPortfolio.get(portfolioId);
  const runtime = runtimes?.find((r) => r.job.id === jobId);
  if (!runtime) {
    return undefined;
  }
  runtime.polls += 1;
  const { job } = runtime;

  if (runtime.polls === 1) {
    // Parsing counted the file — total is now known, work has started.
    runtime.job = {
      ...job,
      status: "RUNNING",
      started_at: new Date().toISOString(),
      total_rows: 4,
      processed_rows: 2,
    };
  } else if (runtime.polls === 2) {
    runtime.job = { ...runtime.job, processed_rows: 3 };
  } else {
    runtime.job = {
      ...runtime.job,
      status: "SUCCEEDED",
      finished_at: new Date().toISOString(),
      total_rows: 4,
      processed_rows: 4,
      created_transactions: 3,
      tickers: ["AAPL", "MSFT"],
      warnings: [
        "Row 5: options trade for AAPL240119C skipped — enter manually.",
        "Row 9: account transfer ignored — enter manually.",
      ],
    };
  }
  return runtime.job;
}

export function listImports(portfolioId: number): StatementImportStatus[] {
  const runtimes = state.jobsByPortfolio.get(portfolioId) ?? [];
  return runtimes.map((r) => r.job);
}
