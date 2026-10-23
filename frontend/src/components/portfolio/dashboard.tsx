"use client";

import * as React from "react";
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
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { AccountSettings } from "@/components/portfolio/account-settings";
import { RetirementImportPanel } from "@/components/portfolio/retirement-import-panel";
import { ReportedHoldings } from "@/components/portfolio/reported-holdings";
import { useReportedAccount } from "@/hooks/use-retirement";
import { Button } from "@/components/ui/button";

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
  const { status, portfolios, selected, selectedId, dataVersion, refreshData, select } =
    usePortfolioSelection();

  React.useEffect(() => {
    if (status !== "success") return;
    const requested = Number(
      new URLSearchParams(window.location.search).get("portfolio"),
    );
    if (portfolios.some((portfolio) => portfolio.id === requested)) select(requested);
  }, [status, portfolios, select]);

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
          <CreatePortfolioDialog
            triggerLabel="Create Portfolio"
            triggerVariant="default"
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <DashboardAccount
      key={selectedId}
      portfolioId={selectedId}
      currency={selected?.base_currency}
      dataVersion={dataVersion}
      refreshData={refreshData}
    />
  );
}

function DashboardAccount({
  portfolioId,
  currency,
  dataVersion,
  refreshData,
}: {
  portfolioId: number;
  currency?: string;
  dataVersion: number;
  refreshData: () => void;
}) {
  const { reloadPortfolios } = usePortfolioSelection();
  const resource = useReportedAccount(portfolioId, dataVersion);
  const [mode, setMode] = React.useState<"reported" | "ledger" | null>(null);
  const [lastDefaultReported, setLastDefaultReported] = React.useState<boolean | null>(null);
  const [listError, setListError] = React.useState("");
  function changed() {
    refreshData();
    void reloadPortfolios().then(
      () => setListError(""),
      () =>
        setListError(
          "Portfolio selector could not refresh. Account panels use freshly loaded account data.",
        ),
    );
  }
  const autoReported =
    resource.status === "success"
      ? resource.data.valuation.status !== "EMPTY" ||
        ["TRADITIONAL_401K", "ROTH_401K", "TRADITIONAL_IRA", "ROTH_IRA"].includes(
          resource.data.account.account_type ?? "UNKNOWN",
        )
      : lastDefaultReported;
  // Retain view policy only, never a previous generation's reported values.
  // The account-keyed parent resets this on selection changes. Updating during
  // render avoids an effect frame that could briefly mount the wrong view.
  if (resource.status === "success" && autoReported !== lastDefaultReported) {
    setLastDefaultReported(autoReported);
  }
  const reported = mode === "reported" || (mode == null && autoReported === true);
  const ledger = mode === "ledger" || (mode == null && autoReported === false);
  return (
    <div className="flex flex-col gap-6">
      <AccountSettings
        portfolioId={portfolioId}
        refreshToken={dataVersion}
        onChanged={changed}
      />
      {listError && <p role="alert">{listError}</p>}
      <nav aria-label="Account valuation view" className="flex gap-2">
        <Button
          variant="outline"
          aria-pressed={reported}
          onClick={() => setMode("reported")}
        >
          Reported Holdings
        </Button>
        <Button
          variant="outline"
          aria-pressed={ledger}
          onClick={() => setMode("ledger")}
        >
          Ledger Analytics
        </Button>
      </nav>
      {resource.status === "loading" ? (
        <p role="status">Loading account valuation…</p>
      ) : resource.status === "error" ? (
        <>
          <ErrorState message={resource.error.message} />
          <Button onClick={refreshData}>Reload Account View</Button>
        </>
      ) : null}
      {reported && resource.status === "success" ? (
        <ReportedHoldings
          valuation={resource.data.valuation}
          securities={resource.data.securities}
        />
      ) : null}
      {ledger ? (
        <>
          <p className="text-sm text-muted-foreground">
            Ledger Analytics: trade-ledger figures only, not a retirement account
            balance. Reported snapshots are never added to these values.
          </p>
          <LegacyLedger
            portfolioId={portfolioId}
            currency={currency}
            dataVersion={dataVersion}
            refreshData={refreshData}
          />
        </>
      ) : null}
      <RetirementImportPanel
        portfolioId={portfolioId}
        refreshToken={dataVersion}
        onSuccess={() => {
          setMode("reported");
          changed();
        }}
      />
    </div>
  );
}

function LegacyLedger({
  portfolioId: selectedId,
  currency,
  dataVersion,
  refreshData,
}: {
  portfolioId: number;
  currency?: string;
  dataVersion: number;
  refreshData: () => void;
}) {
  // Keep the existing dashboard return (summary through Robinhood ImportPanel) here unchanged.
  return (
    <div className="flex flex-col gap-6">
      <PortfolioSummary portfolioId={selectedId} refreshToken={dataVersion} />
      <AllocationSection portfolioId={selectedId} refreshToken={dataVersion} />
      <HoldingsTable
        portfolioId={selectedId}
        refreshToken={dataVersion}
        onChanged={refreshData}
      />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[2fr_1fr]">
        <TransactionLedger
          portfolioId={selectedId}
          refreshToken={dataVersion}
          onDeleted={refreshData}
        />
        <Watchlist />
      </div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <AddPositionForm
          portfolioId={selectedId}
          currency={currency}
          onSuccess={refreshData}
        />
        <ManualTransactionForm
          portfolioId={selectedId}
          currency={currency}
          onSuccess={refreshData}
        />
      </div>
      <ImportPanel
        portfolioId={selectedId}
        currency={currency}
        onSuccess={refreshData}
        refreshToken={dataVersion}
      />
    </div>
  );
}
