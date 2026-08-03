import { env } from "@/lib/env";
import type {
  HoldingInfo,
  LedgerIngestResult,
  PortfolioAnalytics,
  PortfolioCreate,
  PortfolioSummary,
  PositionSnapshot,
  StatementFormat,
  StatementImportStatus,
  Transaction,
  TransactionInput,
} from "@/types/domain";

/**
 * Typed REST client — the ONLY channel the browser uses to reach the backend
 * (§9 frontend/API separation). There is no DB access and no shared server code;
 * every call is a plain HTTP request against the versioned contract, which means
 * the exact same client runs against MSW mocks in tests and the live API in prod.
 */

/** Raised for any non-2xx response so callers can branch on status/URL. */
export class ApiError extends Error {
  readonly status: number;
  readonly url: string;
  /** Backend's human message (FastAPI `{ "detail": ... }`), when present. */
  readonly detail: string | null;

  constructor(status: number, url: string, message: string, detail: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.url = url;
    this.detail = detail;
  }
}

const API_V1 = "/api/v1";

/** Join the configured base URL with a path, avoiding double slashes. */
function url(path: string): string {
  return `${env.apiBaseUrl}${path}`;
}

/**
 * Pull the backend's error message out of a failed response body. FastAPI puts a
 * string (or a validation array) under `detail`; we surface a readable string so
 * callers can show *why* a write failed. Never throws — a non-JSON body → null.
 */
async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.clone().json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") {
        return detail;
      }
      if (Array.isArray(detail) && detail.length > 0) {
        return detail
          .map((item) =>
            item && typeof item === "object" && "msg" in item
              ? String((item as { msg: unknown }).msg)
              : String(item),
          )
          .join("; ");
      }
    }
  } catch {
    // Body was not JSON — fall through to null.
  }
  return null;
}

/** Translate a non-2xx response into a typed {@link ApiError}. */
async function toApiError(
  response: Response,
  method: string,
  path: string,
  target: string,
): Promise<ApiError> {
  const detail = await readErrorDetail(response);
  return new ApiError(
    response.status,
    target,
    detail ?? `${method} ${path} failed with ${response.status}`,
    detail,
  );
}

/**
 * Core GET wrapper: performs the request, enforces JSON, and translates a
 * non-2xx status into a typed {@link ApiError}. Kept generic over the response
 * shape so each endpoint method can name its exact contract type.
 */
async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const target = url(path);
  const response = await fetch(target, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw await toApiError(response, "GET", path, target);
  }
  return (await response.json()) as T;
}

/** Core JSON POST wrapper (accepts any 2xx, including 201). */
async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const target = url(path);
  const response = await fetch(target, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    throw await toApiError(response, "POST", path, target);
  }
  return (await response.json()) as T;
}

/** Multipart POST for file uploads (accepts any 2xx, including 202). */
async function postForm<T>(path: string, form: FormData, signal?: AbortSignal): Promise<T> {
  const target = url(path);
  // NB: do NOT set Content-Type manually — the browser adds the multipart
  // boundary; setting it by hand corrupts the body.
  const response = await fetch(target, {
    method: "POST",
    headers: { Accept: "application/json" },
    body: form,
    signal,
  });

  if (!response.ok) {
    throw await toApiError(response, "POST", path, target);
  }
  return (await response.json()) as T;
}

/** Options for {@link apiClient.createImport}. */
export interface CreateImportOptions {
  /** Broker layout of the upload (defaults to the only supported format today). */
  sourceFormat?: StatementFormat;
  /** Re-import identical content despite the 409 duplicate guard. */
  allowDuplicate?: boolean;
}

/** The versioned API surface, one method per backend route. */
export const apiClient = {
  /** Liveness probe — returns the backend's status map. */
  health(signal?: AbortSignal): Promise<Record<string, string>> {
    return getJson<Record<string, string>>("/health", signal);
  },

  /** Every tracked portfolio — powers the picker. */
  listPortfolios(signal?: AbortSignal): Promise<PortfolioSummary[]> {
    return getJson<PortfolioSummary[]>(`${API_V1}/portfolios`, signal);
  },

  /** Create a new empty portfolio, returning its assigned identity. */
  createPortfolio(body: PortfolioCreate, signal?: AbortSignal): Promise<PortfolioSummary> {
    return postJson<PortfolioSummary>(`${API_V1}/portfolios`, body, signal);
  },

  /** Portfolio identity + base currency. */
  getPortfolio(id: number, signal?: AbortSignal): Promise<PortfolioSummary> {
    return getJson<PortfolioSummary>(`${API_V1}/portfolios/${id}`, signal);
  },

  /** The portfolio's full ledger. */
  listTransactions(id: number, signal?: AbortSignal): Promise<Transaction[]> {
    return getJson<Transaction[]>(`${API_V1}/portfolios/${id}/transactions`, signal);
  },

  /** Append manually-entered ledger events. */
  addTransactions(
    id: number,
    body: TransactionInput[],
    signal?: AbortSignal,
  ): Promise<LedgerIngestResult> {
    return postJson<LedgerIngestResult>(`${API_V1}/portfolios/${id}/transactions`, body, signal);
  },

  /** Record current-holding snapshots as opening BUY lots. */
  addPositions(
    id: number,
    body: PositionSnapshot[],
    signal?: AbortSignal,
  ): Promise<LedgerIngestResult> {
    return postJson<LedgerIngestResult>(`${API_V1}/portfolios/${id}/positions`, body, signal);
  },

  /** Tracked securities + classification metadata. */
  listHoldings(id: number, signal?: AbortSignal): Promise<HoldingInfo[]> {
    return getJson<HoldingInfo[]>(`${API_V1}/portfolios/${id}/holdings`, signal);
  },

  /** Aggregated cost-basis / realized-P&L / XIRR analytics. */
  getAnalytics(id: number, signal?: AbortSignal): Promise<PortfolioAnalytics> {
    return getJson<PortfolioAnalytics>(`${API_V1}/portfolios/${id}/analytics`, signal);
  },

  /**
   * Upload a broker statement for asynchronous import. Returns the initial
   * `202` job record (`PENDING`); poll {@link apiClient.getImport} until the
   * status is terminal. Throws {@link ApiError} on 409 (duplicate), 413 (too
   * large), or 422 (unparseable).
   */
  createImport(
    id: number,
    file: File,
    options: CreateImportOptions = {},
    signal?: AbortSignal,
  ): Promise<StatementImportStatus> {
    const params = new URLSearchParams();
    params.set("source_format", options.sourceFormat ?? "robinhood_csv");
    if (options.allowDuplicate) {
      params.set("allow_duplicate", "true");
    }
    const form = new FormData();
    form.append("file", file);
    return postForm<StatementImportStatus>(
      `${API_V1}/portfolios/${id}/imports?${params.toString()}`,
      form,
      signal,
    );
  },

  /** The portfolio's import history, newest first. */
  listImports(id: number, signal?: AbortSignal): Promise<StatementImportStatus[]> {
    return getJson<StatementImportStatus[]>(`${API_V1}/portfolios/${id}/imports`, signal);
  },

  /** One import job's live status/progress (the endpoint the UI polls). */
  getImport(id: number, jobId: number, signal?: AbortSignal): Promise<StatementImportStatus> {
    return getJson<StatementImportStatus>(`${API_V1}/portfolios/${id}/imports/${jobId}`, signal);
  },
} as const;

export type ApiClient = typeof apiClient;
