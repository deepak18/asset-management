import type {
  LedgerIngestResult,
  PortfolioAnalytics,
  PortfolioCreate,
  PortfolioSummary,
  StatementImportStatus,
} from "@/types/domain";
import {
  analyticsById,
  holdings,
  summariesById,
  transactions,
} from "@/mocks/fixtures";

/**
 * Mutable in-memory state backing the *write* MSW handlers.
 *
 * The read fixtures (portfolios 1/2/99) are static, but create/import/add flows
 * need somewhere to record their effect so the UI can observe it — a picker that
 * shows a just-created portfolio, an import job that visibly progresses across
 * polls. `resetMockState()` restores the seed so Vitest tests stay isolated
 * (called from vitest.setup.ts `afterEach`).
 */

interface JobRuntime {
  job: StatementImportStatus;
  /** How many times this job has been polled — drives the fake progression. */
  polls: number;
}

interface State {
  portfolios: PortfolioSummary[];
  nextPortfolioId: number;
  jobsByPortfolio: Map<number, JobRuntime[]>;
  nextJobId: number;
}

function seed(): State {
  return {
    portfolios: [summariesById[1]!, summariesById[2]!, summariesById[99]!].filter(Boolean),
    nextPortfolioId: 100,
    jobsByPortfolio: new Map(),
    nextJobId: 1,
  };
}

let state: State = seed();

export function resetMockState(): void {
  state = seed();
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

export function getAnalytics(id: number): PortfolioAnalytics | undefined {
  if (analyticsById[id]) {
    return analyticsById[id];
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

export function getHoldings(id: number) {
  if (!findPortfolio(id)) {
    return undefined;
  }
  return id === 1 ? holdings : [];
}

export function ingest(id: number, tickers: string[], count: number): LedgerIngestResult {
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
    return { ok: false, status: 422, detail: "Not a recognizable Robinhood activity CSV." };
  }
  if (lower.includes("duplicate") && !allowDuplicate) {
    return {
      ok: false,
      status: 409,
      detail: "This exact file was already imported. Importing again would double-count it.",
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
  };
  const runtimes = state.jobsByPortfolio.get(portfolioId) ?? [];
  state.jobsByPortfolio.set(portfolioId, [{ job, polls: 0 }, ...runtimes]);
  return { ok: true, job };
}

/** Advance one job a step per poll: PENDING → RUNNING (counted) → SUCCEEDED. */
export function getImport(portfolioId: number, jobId: number): StatementImportStatus | undefined {
  const runtimes = state.jobsByPortfolio.get(portfolioId);
  const runtime = runtimes?.find((r) => r.job.id === jobId);
  if (!runtime) {
    return undefined;
  }
  runtime.polls += 1;
  const { job } = runtime;

  if (runtime.polls === 1) {
    // Parsing counted the file — total is now known, work has started.
    runtime.job = { ...job, status: "RUNNING", started_at: new Date().toISOString(), total_rows: 4, processed_rows: 2 };
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
