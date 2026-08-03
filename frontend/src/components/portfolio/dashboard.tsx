"use client";

import { usePortfolioSelection } from "@/hooks/use-portfolio-selection";
import { PortfolioSummary } from "@/components/portfolio/portfolio-summary";
import { AllocationSection } from "@/components/portfolio/allocation-section";
import { TransactionLedger } from "@/components/portfolio/transaction-ledger";
import { Watchlist } from "@/components/portfolio/watchlist";
import { AddPositionForm } from "@/components/portfolio/add-position-form";
import { ManualTransactionForm } from "@/components/portfolio/manual-transaction-form";
import { ImportPanel } from "@/components/portfolio/import-panel";
import { CreatePortfolioDialog } from "@/components/portfolio/create-portfolio-dialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, LoadingRows } from "@/components/shared/states";

/**
 * Unified Portfolio Dashboard (§1.4).
 *
 * The portfolio id is no longer hard-coded — it comes from the shared selection
 * context (picker in the app shell, persisted in localStorage). Every panel is
 * keyed to the selected id and folds in `dataVersion`, so after any successful
 * write or a finished import the summary, allocation, ledger, and analytics all
 * refetch. With no portfolios at all, we prompt the user to create their first.
 */
export function Dashboard() {
  const { status, portfolios, selected, selectedId, dataVersion, refreshData } =
    usePortfolioSelection();

  if (status === "loading") {
    return <LoadingRows rows={6} />;
  }
  if (status === "error") {
    return <ErrorState message="Could not load your portfolios." />;
  }
  if (portfolios.length === 0 || selectedId == null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No portfolios yet</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-start gap-3">
          <p className="text-sm text-muted-foreground">
            Create your first portfolio to start tracking holdings and analytics.
          </p>
          <CreatePortfolioDialog triggerLabel="Create portfolio" triggerVariant="default" />
        </CardContent>
      </Card>
    );
  }

  const currency = selected?.base_currency;

  return (
    <div className="flex flex-col gap-6">
      <PortfolioSummary portfolioId={selectedId} refreshToken={dataVersion} />
      <AllocationSection portfolioId={selectedId} refreshToken={dataVersion} />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[2fr_1fr]">
        <TransactionLedger portfolioId={selectedId} refreshToken={dataVersion} />
        <Watchlist />
      </div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <AddPositionForm portfolioId={selectedId} currency={currency} onSuccess={refreshData} />
        <ManualTransactionForm
          portfolioId={selectedId}
          currency={currency}
          onSuccess={refreshData}
        />
      </div>
      <ImportPanel portfolioId={selectedId} currency={currency} onSuccess={refreshData} />
    </div>
  );
}
