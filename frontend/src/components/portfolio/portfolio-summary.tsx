"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingRows } from "@/components/shared/states";
import { usePortfolioAnalytics } from "@/hooks/use-portfolio";
import { DASH, formatMoney, formatPercent, signTone } from "@/lib/format";
import type { PortfolioAnalytics } from "@/types/domain";

/** A single labelled figure with sign-aware coloring. */
function StatCard({
  label,
  value,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: string;
  tone?: "neutral" | "positive" | "negative" | "unknown";
  hint?: string;
}) {
  const toneClass =
    tone === "positive"
      ? "text-positive"
      : tone === "negative"
        ? "text-destructive"
        : tone === "unknown"
          ? "text-muted-foreground"
          : "text-foreground";
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className={`text-2xl font-semibold tabular-nums ${toneClass}`}>{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

/** Map a Decimal-string sign to a StatCard tone (unknown = not computed). */
function toneFor(raw: string | null | undefined): "positive" | "negative" | "unknown" | "neutral" {
  const tone = signTone(raw);
  if (tone === "positive") return "positive";
  if (tone === "negative") return "negative";
  if (tone === "unknown") return "unknown";
  return "neutral";
}

function SummaryGrid({ analytics }: { analytics: PortfolioAnalytics }) {
  const ccy = analytics.base_currency;
  const isUnpriced = analytics.market_value_base == null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">{analytics.portfolio.name}</h2>
          <p className="text-sm text-muted-foreground">
            Base currency {analytics.base_currency}
          </p>
        </div>
        {isUnpriced ? (
          <Badge variant="muted">Not priced</Badge>
        ) : (
          <Badge variant="outline">
            Priced {analytics.priced_as_of?.slice(0, 10) ?? DASH}
          </Badge>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard
          label="Market value"
          value={formatMoney(analytics.market_value_base, ccy)}
          hint={isUnpriced ? "Awaiting market data" : undefined}
        />
        <StatCard
          label="Unrealized P&L"
          value={formatMoney(analytics.unrealized_pnl_base, ccy, { signed: true })}
          tone={toneFor(analytics.unrealized_pnl_base)}
        />
        <StatCard
          label="Realized P&L"
          value={formatMoney(analytics.realized_pnl_base, ccy, { signed: true })}
          tone={toneFor(analytics.realized_pnl_base)}
        />
        <StatCard
          label="Open cost basis"
          value={formatMoney(analytics.open_cost_basis_base, ccy)}
        />
        <StatCard
          label="Dividends"
          value={formatMoney(analytics.dividends_base, ccy)}
        />
        <StatCard
          label="Money-weighted return (XIRR)"
          value={formatPercent(analytics.money_weighted_return, { signed: true })}
          tone={toneFor(analytics.money_weighted_return)}
          hint={analytics.money_weighted_return == null ? "Not computable" : undefined}
        />
      </div>

      {analytics.unpriced_tickers.length > 0 ? (
        <EmptyState
          message={`Unpriced: ${analytics.unpriced_tickers.join(", ")}`}
          className="italic"
        />
      ) : null}
    </div>
  );
}

/**
 * Portfolio Summary overview. Reads analytics from the typed client and renders
 * headline figures. Market-value-dependent stats show "—" / "Not priced" when
 * the backend could not price the book — never a fabricated zero. `refreshToken`
 * lets the dashboard force a refetch after a write/import lands.
 */
export function PortfolioSummary({
  portfolioId,
  refreshToken = 0,
}: {
  portfolioId: number;
  refreshToken?: number;
}) {
  const state = usePortfolioAnalytics(portfolioId, refreshToken);

  if (state.status === "loading") {
    return <LoadingRows rows={4} />;
  }
  if (state.status === "error") {
    return <ErrorState message="Could not load portfolio analytics." />;
  }
  return <SummaryGrid analytics={state.data} />;
}
