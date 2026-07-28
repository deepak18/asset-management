import { env } from "@/lib/env";
import type {
  HoldingInfo,
  PortfolioAnalytics,
  PortfolioSummary,
  Transaction,
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

  constructor(status: number, url: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.url = url;
  }
}

const API_V1 = "/api/v1";

/** Join the configured base URL with a path, avoiding double slashes. */
function url(path: string): string {
  return `${env.apiBaseUrl}${path}`;
}

/**
 * Core fetch wrapper: performs the request, enforces JSON, and translates a
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
    throw new ApiError(
      response.status,
      target,
      `GET ${path} failed with ${response.status}`,
    );
  }
  return (await response.json()) as T;
}

/** The versioned API surface, one method per backend route. */
export const apiClient = {
  /** Liveness probe — returns the backend's status map. */
  health(signal?: AbortSignal): Promise<Record<string, string>> {
    return getJson<Record<string, string>>("/health", signal);
  },

  /** Portfolio identity + base currency. */
  getPortfolio(id: number, signal?: AbortSignal): Promise<PortfolioSummary> {
    return getJson<PortfolioSummary>(`${API_V1}/portfolios/${id}`, signal);
  },

  /** The portfolio's full ledger. */
  listTransactions(id: number, signal?: AbortSignal): Promise<Transaction[]> {
    return getJson<Transaction[]>(`${API_V1}/portfolios/${id}/transactions`, signal);
  },

  /** Tracked securities + classification metadata. */
  listHoldings(id: number, signal?: AbortSignal): Promise<HoldingInfo[]> {
    return getJson<HoldingInfo[]>(`${API_V1}/portfolios/${id}/holdings`, signal);
  },

  /** Aggregated cost-basis / realized-P&L / XIRR analytics. */
  getAnalytics(id: number, signal?: AbortSignal): Promise<PortfolioAnalytics> {
    return getJson<PortfolioAnalytics>(`${API_V1}/portfolios/${id}/analytics`, signal);
  },
} as const;

export type ApiClient = typeof apiClient;
