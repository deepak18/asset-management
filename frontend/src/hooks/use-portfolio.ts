"use client";

import { apiClient } from "@/lib/api-client";
import { useApiResource, type AsyncState } from "@/hooks/use-api-resource";
import type {
  HoldingAnalytics,
  HoldingInfo,
  PortfolioAnalytics,
  PortfolioSummary,
  Transaction,
} from "@/types/domain";

/**
 * Endpoint-specific hooks that bind the typed API client to {@link useApiResource}.
 *
 * Components depend on these (not on `fetch` or hard-coded data), so swapping
 * MSW mocks for the live backend is invisible to the UI — the seam is the client.
 *
 * Each per-portfolio hook takes an optional `version` token: bumping it (after a
 * successful write or a finished import) forces a refetch so the dashboard shows
 * freshly-ingested data without a full reload.
 */

export function usePortfolios(version = 0): AsyncState<PortfolioSummary[]> {
  return useApiResource(() => apiClient.listPortfolios(), [version]);
}

export function usePortfolioSummary(
  id: number,
  version = 0,
): AsyncState<PortfolioSummary> {
  return useApiResource(() => apiClient.getPortfolio(id), [id, version]);
}

export function usePortfolioAnalytics(
  id: number,
  version = 0,
): AsyncState<PortfolioAnalytics> {
  return useApiResource(() => apiClient.getAnalytics(id), [id, version]);
}

export function useTransactions(id: number, version = 0): AsyncState<Transaction[]> {
  return useApiResource(() => apiClient.listTransactions(id), [id, version]);
}

export function useHoldings(id: number, version = 0): AsyncState<HoldingInfo[]> {
  return useApiResource(() => apiClient.listHoldings(id), [id, version]);
}

export function useHolding(
  id: number,
  ticker: string,
  version = 0,
): AsyncState<HoldingInfo> {
  return useApiResource(() => apiClient.getHolding(id, ticker), [id, ticker, version]);
}

/**
 * This holding's own money-weighted return (XIRR), scoped to the URL portfolio +
 * ticker. Keyed on `[id, ticker, version]` so navigating to a different holding
 * refetches (and {@link useApiResource}'s stale-response guard discards a late
 * answer from the previous ticker after navigation or unmount).
 */
export function useHoldingAnalytics(
  id: number,
  ticker: string,
  version = 0,
): AsyncState<HoldingAnalytics> {
  return useApiResource(
    () => apiClient.getHoldingAnalytics(id, ticker),
    [id, ticker, version],
  );
}
