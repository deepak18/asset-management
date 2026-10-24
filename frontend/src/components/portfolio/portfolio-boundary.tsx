"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { usePortfolioSelection } from "@/hooks/use-portfolio-selection";
import { CreatePortfolioDialog } from "./create-portfolio-dialog";
import { ErrorState, LoadingRows } from "@/components/shared/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface PortfolioPageScope {
  portfolioId: number;
  name: string;
  currency?: string;
  dataVersion: number;
  refreshData: () => void;
  changed: () => void;
  listError: string;
}

export function PortfolioBoundary({
  children,
}: {
  children: (scope: PortfolioPageScope) => React.ReactNode;
}) {
  return (
    <React.Suspense fallback={<LoadingRows rows={6} />}>
      <QueryBoundary>{children}</QueryBoundary>
    </React.Suspense>
  );
}

function QueryBoundary({
  children,
}: {
  children: (scope: PortfolioPageScope) => React.ReactNode;
}) {
  const query = useSearchParams().get("portfolio");
  const selection = usePortfolioSelection();
  const { status, portfolios, selectedId, selected, select } = selection;
  const [appliedQuery, setAppliedQuery] = React.useState<string | null | undefined>(
    undefined,
  );
  React.useEffect(() => {
    if (status !== "success") return;
    const requested = Number(query);
    if (portfolios.some((portfolio) => portfolio.id === requested)) select(requested);
    // Route-entry synchronization must complete before account panels mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAppliedQuery(query);
    // React to URL changes (including back/forward), never metadata refreshes
    // or picker changes with the same query.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, select, query]);
  if (status === "error")
    return <ErrorState message="Could not load your portfolios." />;
  if (status === "loading" || appliedQuery !== query) return <LoadingRows rows={6} />;
  if (portfolios.length === 0 || selectedId == null)
    return (
      <Card>
        <CardHeader>
          <CardTitle>No portfolios yet</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p>Create your first portfolio to start tracking holdings and analytics.</p>
          <CreatePortfolioDialog
            triggerLabel="Create Portfolio"
            triggerVariant="default"
          />
        </CardContent>
      </Card>
    );
  return (
    <SelectedAccount
      key={selectedId}
      selection={selection}
      name={selected?.name ?? `Portfolio ${selectedId}`}
    >
      {children}
    </SelectedAccount>
  );
}

function SelectedAccount({
  selection,
  name,
  children,
}: {
  selection: ReturnType<typeof usePortfolioSelection>;
  name: string;
  children: (scope: PortfolioPageScope) => React.ReactNode;
}) {
  const [listError, setListError] = React.useState("");
  const mounted = React.useRef(true);
  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const changed = React.useCallback(() => {
    selection.refreshData();
    void selection.reloadPortfolios().then(
      () => {
        if (mounted.current) setListError("");
      },
      () => {
        if (mounted.current)
          setListError(
            "Portfolio selector could not refresh. Account panels use freshly loaded account data.",
          );
      },
    );
  }, [selection]);
  // The callback receives an event handler; mounted.current is read only after writes.
  // eslint-disable-next-line react-hooks/refs
  return children({
    portfolioId: selection.selectedId!,
    name,
    currency: selection.selected?.base_currency,
    dataVersion: selection.dataVersion,
    refreshData: selection.refreshData,
    changed,
    listError,
  });
}
