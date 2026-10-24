"use client";

import * as React from "react";
import { PortfolioSummary } from "@/components/portfolio/portfolio-summary";
import { AllocationSection } from "@/components/portfolio/allocation-section";
import { TransactionLedger } from "@/components/portfolio/transaction-ledger";
import { Watchlist } from "@/components/portfolio/watchlist";
import { AddPositionForm } from "@/components/portfolio/add-position-form";
import { ManualTransactionForm } from "@/components/portfolio/manual-transaction-form";
import { ErrorState } from "@/components/shared/states";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { AccountSettings } from "@/components/portfolio/account-settings";
import { ReportedHoldings } from "@/components/portfolio/reported-holdings";
import { useReportedAccount } from "@/hooks/use-retirement";
import { Button } from "@/components/ui/button";
import { PortfolioBoundary, type PortfolioPageScope } from "./portfolio-boundary";
import { ImportsPage } from "./imports-page";
import { PortfolioLinks } from "@/components/app-shell/portfolio-links";

export type PortfolioPage = "overview" | "holdings" | "ledger" | "imports" | "settings";

/** Each route owns its forms; only the layout's portfolio selection persists. */
export function Dashboard({ page = "overview" }: { page?: PortfolioPage }) {
  return (
    <PortfolioBoundary>
      {(scope) => (
        <AccountPage key={`${page}:${scope.portfolioId}`} page={page} {...scope} />
      )}
    </PortfolioBoundary>
  );
}

function AccountPage({ page, ...scope }: PortfolioPageScope & { page: PortfolioPage }) {
  const { portfolioId, dataVersion, refreshData, changed, listError } = scope;
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">{scope.name}</p>
        <h1 className="text-2xl font-semibold tracking-tight">
          {
            {
              overview: "Account Overview",
              holdings: "Reported Holdings",
              ledger: "Ledger Analytics",
              imports: "Statement Imports",
              settings: "Account Settings",
            }[page]
          }
        </h1>
        <p className="text-sm text-muted-foreground">
          Reported snapshots and trade-ledger values are separate views, never combined.
        </p>
      </div>
      {listError && <p role="alert">{listError}</p>}
      {page === "settings" ? (
        <AccountSettings
          portfolioId={portfolioId}
          refreshToken={dataVersion}
          onChanged={changed}
        />
      ) : page === "imports" ? (
        <ImportsPage {...scope} />
      ) : page === "ledger" ? (
        <LegacyLedger {...scope} />
      ) : (
        <AccountValuation {...scope} automatic={page === "overview"} />
      )}
      <PortfolioLinks
        portfolioId={portfolioId}
        activePath={page === "overview" ? "/" : `/${page}`}
        label="Account destinations"
      />
      {page === "settings" && (
        <Button variant="outline" onClick={refreshData}>
          Reload Account Settings
        </Button>
      )}
    </div>
  );
}

function AccountValuation({
  automatic,
  ...scope
}: PortfolioPageScope & { automatic: boolean }) {
  const { portfolioId, dataVersion, refreshData } = scope;
  const resource = useReportedAccount(portfolioId, dataVersion);
  const [lastDefaultReported, setLastDefaultReported] = React.useState<boolean | null>(
    null,
  );
  const autoReported =
    resource.status === "success"
      ? resource.data.valuation.status !== "EMPTY" ||
        ["TRADITIONAL_401K", "ROTH_401K", "TRADITIONAL_IRA", "ROTH_IRA"].includes(
          resource.data.account.account_type ?? "UNKNOWN",
        )
      : lastDefaultReported;
  // Preserve only view policy through refreshes, never stale reported figures.
  if (resource.status === "success" && autoReported !== lastDefaultReported)
    setLastDefaultReported(autoReported);
  const reported = !automatic || autoReported === true;
  return (
    <>
      {resource.status === "loading" ? (
        <p role="status">Loading account valuation…</p>
      ) : resource.status === "error" ? (
        <>
          <ErrorState message={resource.error.message} />
          <Button onClick={refreshData}>Reload Account View</Button>
        </>
      ) : reported ? (
        <ReportedHoldings
          valuation={resource.data.valuation}
          securities={resource.data.securities}
        />
      ) : null}
      {automatic && autoReported === false ? <LegacyLedger {...scope} /> : null}
    </>
  );
}

function LegacyLedger({
  portfolioId: selectedId,
  currency,
  dataVersion,
  refreshData,
}: PortfolioPageScope) {
  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-muted-foreground">
        Ledger Analytics: trade-ledger figures only, not a retirement account balance.
        Reported snapshots are never added to these values.
      </p>
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
    </div>
  );
}
