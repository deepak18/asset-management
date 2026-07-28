"use client";

import { apiClient } from "@/lib/api-client";
import { useApiResource, type AsyncState } from "@/hooks/use-api-resource";
import type {
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
 */

export function usePortfolioSummary(id: number): AsyncState<PortfolioSummary> {
  return useApiResource(() => apiClient.getPortfolio(id), [id]);
}

export function usePortfolioAnalytics(id: number): AsyncState<PortfolioAnalytics> {
  return useApiResource(() => apiClient.getAnalytics(id), [id]);
}

export function useTransactions(id: number): AsyncState<Transaction[]> {
  return useApiResource(() => apiClient.listTransactions(id), [id]);
}

export function useHoldings(id: number): AsyncState<HoldingInfo[]> {
  return useApiResource(() => apiClient.listHoldings(id), [id]);
}
