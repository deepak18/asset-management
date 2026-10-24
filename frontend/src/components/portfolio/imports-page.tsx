"use client";

import * as React from "react";
import Link from "next/link";
import { ImportPanel } from "./import-panel";
import { RetirementImportPanel } from "./retirement-import-panel";
import type { PortfolioPageScope } from "./portfolio-boundary";

export function ImportsPage({
  portfolioId,
  currency,
  dataVersion,
  changed,
}: PortfolioPageScope) {
  const [brokerage, setBrokerage] = React.useState<"robinhood" | "vanguard">(
    "robinhood",
  );
  const [completed, setCompleted] = React.useState(false);
  const uid = React.useId();
  function succeeded() {
    setCompleted(true);
    changed();
  }
  return (
    <section aria-label="Statement import workspace" className="space-y-4">
      <div className="rounded-lg border bg-muted/30 p-4">
        <label htmlFor={uid} className="mb-2 block font-medium">
          Brokerage
        </label>
        <select
          id={uid}
          className="w-full rounded-md border bg-background p-2 sm:w-72"
          value={brokerage}
          onChange={(event) => {
            setBrokerage(event.target.value === "vanguard" ? "vanguard" : "robinhood");
            setCompleted(false);
          }}
          aria-describedby={`${uid}-help`}
        >
          <option value="robinhood">Robinhood</option>
          <option value="vanguard">Vanguard</option>
        </select>
        <p id={`${uid}-help`} className="mt-2 text-sm text-muted-foreground">
          Robinhood activity updates the trade ledger. Vanguard holdings and observed
          activity update the separate reported account view. Switching brokerage
          discards the current review and upload state.
        </p>
      </div>
      {brokerage === "robinhood" ? (
        <ImportPanel
          key="robinhood"
          portfolioId={portfolioId}
          currency={currency}
          refreshToken={dataVersion}
          onSuccess={succeeded}
        />
      ) : (
        <RetirementImportPanel
          key="vanguard"
          portfolioId={portfolioId}
          refreshToken={dataVersion}
          onSuccess={succeeded}
        />
      )}
      {completed && (
        <p role="status">
          Import data refreshed.{" "}
          <Link
            className="underline"
            href={`/${brokerage === "vanguard" ? "holdings" : "ledger"}?portfolio=${portfolioId}`}
          >
            View {brokerage === "vanguard" ? "Reported Holdings" : "Ledger Analytics"}
          </Link>
        </p>
      )}
    </section>
  );
}
