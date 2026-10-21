"use client";

import * as React from "react";
import Link from "next/link";
import { ApiError } from "@/lib/api-client";
import {
  useHolding,
  useHoldingAnalytics,
  usePortfolioAnalytics,
} from "@/hooks/use-portfolio";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ErrorState, LoadingRows } from "@/components/shared/states";
import { HoldingClassificationCell } from "./holding-classification-cell";
import { HoldingDataGaps } from "./holding-data-gaps";
import { TransactionLedger } from "./transaction-ledger";
import { HoldingHistory } from "./holding-history";
import {
  DASH,
  formatMoney,
  formatPercent,
  formatQuantity,
  signTone,
} from "@/lib/format";
import type {
  HoldingAnalytics,
  HoldingInfo,
  HoldingReturnStatus,
} from "@/types/domain";

/**
 * Why this holding's XIRR is withheld, phrased as the action that would fix it.
 *
 * Each reason needs a different response — more history vs. market-data config vs.
 * a missing FX rate vs. a source-data repair — so the status travels with the
 * (null) value and we explain it. None of these is ever rendered as `0`: that
 * would assert a return the backend explicitly declined to compute.
 */
const RETURN_GUIDANCE: Record<HoldingReturnStatus, string> = {
  OK: "Return not reported for this holding.",
  INCOMPLETE_HISTORY:
    "Incomplete history — this holding only has a snapshot or an unconfirmed import. Import its full dated transactions to compute a return.",
  UNPRICED_POSITION:
    "Connect market data — this holding's return needs today's price as its terminal value.",
  MISSING_FX:
    "Missing FX rate — add the exchange rate from this holding's currency to the portfolio base currency.",
  INSUFFICIENT_FLOWS:
    "Needs more history — a single dated cash flow has no rate of return.",
  INVALID_HISTORY:
    "History needs review — this holding's transactions can't produce a valid return.",
};

/** The provenance/date line for a *computed* return, only from supplied metadata. */
function valuationNote(analytics: HoldingAnalytics): string | null {
  if (analytics.valuation_source === "QUOTE" && analytics.valuation_provenance) {
    const { provider_code, source_table, as_of } = analytics.valuation_provenance;
    return `Valued ${analytics.valuation_date} from ${provider_code} ${source_table} (quote as of ${as_of.slice(0, 10)}).`;
  }
  if (analytics.valuation_source === "LEDGER") {
    return `Valued from the final ledger entry on ${analytics.valuation_date} (closed position).`;
  }
  return null;
}

/** Sign-aware color for a computed return (zero/neutral stays muted-foreground). */
function returnToneClass(raw: string | null | undefined): string {
  const tone = signTone(raw);
  if (tone === "positive") return "text-positive";
  if (tone === "negative") return "text-destructive";
  return "text-foreground";
}

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
  const holding = useHolding(portfolioId, ticker, version);
  const analytics = usePortfolioAnalytics(portfolioId, version);
  const holdingReturn = useHoldingAnalytics(portfolioId, ticker, version);
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
        <HoldingHistory holding={record} />
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
      <Card>
        <CardHeader>
          <CardTitle>This holding&apos;s money-weighted return (XIRR)</CardTitle>
        </CardHeader>
        <CardContent>
          <HoldingReturnBody state={holdingReturn} ticker={record.ticker} />
        </CardContent>
      </Card>
      <TransactionLedger
        portfolioId={portfolioId}
        ticker={ticker}
        refreshToken={version}
        onDeleted={() => {
          setEdited(null);
          setVersion((current) => current + 1);
        }}
      />
    </div>
  );
}

/**
 * Renders the holding-scoped XIRR, split so loading/error/404 of *this* request
 * never disables the classification editor or the ledger above it. A computed
 * return is formatted with the existing percentage conventions (legitimate zero
 * and negative values included); a withheld one reads as a dash plus the
 * status-specific reason, never a fabricated 0.
 */
function HoldingReturnBody({
  state,
  ticker,
}: {
  state: ReturnType<typeof useHoldingAnalytics>;
  ticker: string;
}) {
  if (state.status === "loading") {
    return <LoadingRows rows={1} />;
  }
  if (state.status === "error") {
    const missing = state.error instanceof ApiError && state.error.status === 404;
    return (
      <p className="text-sm text-muted-foreground">
        {missing
          ? "No return reported for this holding."
          : "Could not load this holding's return. Classification editing still works."}
      </p>
    );
  }
  const analytics = state.data;
  const computed =
    analytics.money_weighted_return_status === "OK" &&
    analytics.money_weighted_return != null;
  if (computed) {
    const note = valuationNote(analytics);
    return (
      <>
        <p
          className={`text-2xl font-semibold tabular-nums ${returnToneClass(
            analytics.money_weighted_return,
          )}`}
        >
          {formatPercent(analytics.money_weighted_return, { signed: true })}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Annualized money-weighted return on your {ticker} cash flows.
        </p>
        {note ? <p className="mt-1 text-sm text-muted-foreground">{note}</p> : null}
      </>
    );
  }
  return (
    <>
      <p className="text-2xl font-semibold tabular-nums text-muted-foreground">
        {DASH}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        {RETURN_GUIDANCE[analytics.money_weighted_return_status]}
      </p>
    </>
  );
}
