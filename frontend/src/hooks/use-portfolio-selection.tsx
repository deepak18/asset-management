"use client";

import * as React from "react";
import { apiClient } from "@/lib/api-client";
import type { PortfolioSummary } from "@/types/domain";

const STORAGE_KEY = "am.selected.portfolio";

/**
 * Shared state for "which portfolio is the dashboard showing?".
 *
 * The picker lives in the app shell while the panels live in the page, so the
 * selected id can't be a local `useState` — it's lifted into this context and
 * mirrored to `localStorage` so a reload reopens the same book. `dataVersion` is
 * a monotonically-increasing token every per-portfolio hook folds into its deps;
 * bumping it via {@link PortfolioSelectionValue.refreshData} forces analytics /
 * holdings / transactions to refetch after a successful write or import.
 */
export interface PortfolioSelectionValue {
  status: "loading" | "error" | "success";
  portfolios: PortfolioSummary[];
  selectedId: number | null;
  selected: PortfolioSummary | null;
  select: (id: number) => void;
  /** Refetch the portfolio list (after creating one) and return the new list. */
  reloadPortfolios: () => Promise<PortfolioSummary[]>;
  /** Refetch the list, then select the given id (used after create). */
  reloadAndSelect: (id: number) => Promise<void>;
  dataVersion: number;
  refreshData: () => void;
}

const PortfolioSelectionContext = React.createContext<PortfolioSelectionValue | null>(null);

function readStoredId(): number | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function persistId(id: number | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (id == null) {
    window.localStorage.removeItem(STORAGE_KEY);
  } else {
    window.localStorage.setItem(STORAGE_KEY, String(id));
  }
}

export function PortfolioSelectionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<"loading" | "error" | "success">("loading");
  const [portfolios, setPortfolios] = React.useState<PortfolioSummary[]>([]);
  const [selectedId, setSelectedId] = React.useState<number | null>(null);
  const [dataVersion, setDataVersion] = React.useState(0);

  // Reconcile the selection against a freshly-loaded list: keep the stored id if
  // it still exists, otherwise fall back to the first portfolio (or null when
  // there are none, so the UI can prompt to create one).
  const reconcileSelection = React.useCallback((list: PortfolioSummary[]) => {
    setSelectedId((current) => {
      const stored = current ?? readStoredId();
      const exists = stored != null && list.some((p) => p.id === stored);
      const next = exists ? stored : (list[0]?.id ?? null);
      persistId(next);
      return next;
    });
  }, []);

  const reloadPortfolios = React.useCallback(async (): Promise<PortfolioSummary[]> => {
    const list = await apiClient.listPortfolios();
    setPortfolios(list);
    setStatus("success");
    reconcileSelection(list);
    return list;
  }, [reconcileSelection]);

  // Initial load.
  React.useEffect(() => {
    let active = true;
    apiClient
      .listPortfolios()
      .then((list) => {
        if (!active) return;
        setPortfolios(list);
        setStatus("success");
        reconcileSelection(list);
      })
      .catch(() => {
        if (active) setStatus("error");
      });
    return () => {
      active = false;
    };
  }, [reconcileSelection]);

  const select = React.useCallback((id: number) => {
    setSelectedId(id);
    persistId(id);
  }, []);

  const reloadAndSelect = React.useCallback(
    async (id: number) => {
      const list = await apiClient.listPortfolios();
      setPortfolios(list);
      setStatus("success");
      setSelectedId(id);
      persistId(id);
    },
    [],
  );

  const refreshData = React.useCallback(() => {
    setDataVersion((v) => v + 1);
  }, []);

  const selected = React.useMemo(
    () => portfolios.find((p) => p.id === selectedId) ?? null,
    [portfolios, selectedId],
  );

  const value = React.useMemo<PortfolioSelectionValue>(
    () => ({
      status,
      portfolios,
      selectedId,
      selected,
      select,
      reloadPortfolios,
      reloadAndSelect,
      dataVersion,
      refreshData,
    }),
    [status, portfolios, selectedId, selected, select, reloadPortfolios, reloadAndSelect, dataVersion, refreshData],
  );

  return (
    <PortfolioSelectionContext.Provider value={value}>
      {children}
    </PortfolioSelectionContext.Provider>
  );
}

/** Access the portfolio-selection context (throws outside the provider). */
export function usePortfolioSelection(): PortfolioSelectionValue {
  const ctx = React.useContext(PortfolioSelectionContext);
  if (ctx === null) {
    throw new Error("usePortfolioSelection must be used within a PortfolioSelectionProvider");
  }
  return ctx;
}
