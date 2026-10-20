"use client";

import * as React from "react";
import Link from "next/link";
import { ApiError } from "@/lib/api-client";
import { useHolding, usePortfolioAnalytics } from "@/hooks/use-portfolio";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ErrorState, LoadingRows } from "@/components/shared/states";
import { HoldingClassificationCell } from "./holding-classification-cell";
import { HoldingDataGaps } from "./holding-data-gaps";
import { TransactionLedger } from "./transaction-ledger";
import { formatMoney, formatQuantity } from "@/lib/format";
import { xirrPresentation } from "./portfolio-summary";
import type { HoldingInfo } from "@/types/domain";

export function HoldingDetail(props: { portfolioId: number; ticker: string }) {
  return (
    <HoldingDetailForTicker key={`${props.portfolioId}:${props.ticker}`} {...props} />
  );
}

function HoldingDetailForTicker({
  portfolioId,
  ticker,
}: {
  portfolioId: number;
  ticker: string;
}) {
  const [version, setVersion] = React.useState(0);
  const [edited, setEdited] = React.useState<HoldingInfo | null>(null);
  const holding = useHolding(portfolioId, ticker);
  const analytics = usePortfolioAnalytics(portfolioId, version);
  const back = (
    <Link className="underline" href={`/?portfolio=${portfolioId}`}>
      ← Back to portfolio
    </Link>
  );
  if (holding.status === "loading")
    return (
      <div>
        {back}
        <LoadingRows rows={4} />
      </div>
    );
  if (holding.status === "error")
    return (
      <div>
        {back}
        <ErrorState
          message={
            holding.error instanceof ApiError && holding.error.status === 404
              ? "Holding not found in this portfolio."
              : "Could not load holding."
          }
        />
      </div>
    );
  const record = edited ?? holding.data;
  const data = analytics.status === "success" ? analytics.data : null;
  const position = data?.positions.find((row) => row.ticker === ticker);
  const value = data?.positions_unrealized.find((row) => row.ticker === ticker);
  const currency = data?.base_currency ?? "";
  const gaps = [...new Set([...record.data_gaps, ...(position?.data_gaps ?? [])])];
  const xirr = data ? xirrPresentation(data) : null;
  const refresh = (updated: HoldingInfo) => {
    setEdited(updated);
    setVersion((current) => current + 1);
  };
  const figures = [
    ["Quantity", formatQuantity(position?.open_quantity)],
    ["Open cost basis", formatMoney(position?.open_cost_basis_base, currency)],
    [
      "Market value",
      formatMoney(
        value?.market_value_base ??
          data?.allocation_by_ticker.find((row) => row.key === ticker)?.market_value,
        currency,
      ),
    ],
    [
      "Unrealized P&L",
      formatMoney(value?.unrealized_pnl_base, currency, { signed: true }),
    ],
    [
      "Realized P&L",
      formatMoney(position?.realized_pnl_base, currency, { signed: true }),
    ],
    ["Dividends", formatMoney(position?.dividends_base, currency)],
  ];

  return (
    <div className="space-y-6">
      {back}
      <header>
        <h1 className="text-2xl font-semibold">{record.ticker}</h1>
        <p className="text-muted-foreground">
          {data?.portfolio.name ?? `Portfolio ${portfolioId}`} · Position values in{" "}
          {currency || "portfolio base currency"}
        </p>
        <HoldingDataGaps gaps={gaps} />
      </header>
      <Card>
        <CardHeader>
          <CardTitle>Position overview</CardTitle>
        </CardHeader>
        <CardContent>
          {analytics.status === "loading" ? (
            <LoadingRows rows={2} />
          ) : analytics.status === "error" ? (
            <ErrorState message="Could not load position values. Classification editing still works." />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-4 lg:grid-cols-3">
                {figures.map(([label, text]) => (
                  <div key={label}>
                    <dt className="text-sm text-muted-foreground">{label}</dt>
                    <dd className="font-semibold tabular-nums">{text}</dd>
                  </div>
                ))}
              </dl>
              {data?.unpriced_tickers.includes(ticker) ? (
                <p className="mt-3">
                  Price unavailable — connect market data or check provider
                  availability.
                </p>
              ) : null}
              {!position ? (
                <p className="mt-3">No ledger position reported for this holding.</p>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Classification</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Source: {record.classification_source}. Manual edits are protected from
            automatic classification unless refresh is explicitly requested.
          </p>
          {(["sector", "industry"] as const).map((field) => (
            <div key={field}>
              <h3 className="font-medium capitalize">{field}</h3>
              <HoldingClassificationCell
                portfolioId={portfolioId}
                holding={record}
                field={field}
                onChanged={refresh}
              />
            </div>
          ))}
        </CardContent>
      </Card>
      {xirr ? (
        <Card>
          <CardHeader>
            <CardTitle>Portfolio money-weighted return (XIRR)</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-semibold">{xirr.value}</p>
            {xirr.hint ? <p>{xirr.hint}</p> : null}
            <p className="text-sm text-muted-foreground">
              This return is for the whole portfolio, not this ticker. The API does not
              expose a per-holding XIRR.
            </p>
          </CardContent>
        </Card>
      ) : null}
      <TransactionLedger
        portfolioId={portfolioId}
        ticker={ticker}
        refreshToken={version}
      />
    </div>
  );
}
