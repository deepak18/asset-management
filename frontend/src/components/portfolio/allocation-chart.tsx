"use client";

import * as React from "react";
import { Cell, Pie, PieChart } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/shared/states";
import { formatMoney, formatPercent } from "@/lib/format";
import { parseDecimal } from "@/lib/decimal";
import type { AllocationWeight } from "@/types/domain";

const CHART_COLORS = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
];

/**
 * Convert a weight fraction string to a number *for arc geometry only*.
 *
 * This is the one place a float is acceptable: it sizes the SVG wedge, a purely
 * visual proportion. Every number the user actually reads (legend percent and
 * market value) is formatted from the original Decimal string, so no displayed
 * figure is ever derived from a float.
 */
function weightToArcValue(weight: string): number {
  const parsed = parseDecimal(weight);
  if (parsed === null) {
    return 0;
  }
  const asNumber = Number(`${parsed.negative ? "-" : ""}${parsed.int}.${parsed.frac || "0"}`);
  return Number.isFinite(asNumber) && asNumber > 0 ? asNumber : 0;
}

/**
 * A donut breakdown for one allocation dimension (sector or industry).
 *
 * When `rows` is empty — the honest signal that the book is unpriced — we show a
 * "not priced" message instead of an empty ring, per the no-fake-zero rule.
 */
export function AllocationChart({
  title,
  rows,
  currency,
}: {
  title: string;
  rows: AllocationWeight[];
  currency: string;
}) {
  const data = React.useMemo(
    () => rows.map((row) => ({ ...row, arc: weightToArcValue(row.weight) })),
    [rows],
  );
  const hasArc = data.some((d) => d.arc > 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <EmptyState message="Not priced — allocation unavailable." />
        ) : (
          <div className="flex flex-col items-center gap-4 sm:flex-row">
            {hasArc ? (
              <PieChart width={160} height={160} role="img" aria-label={`${title} donut`}>
                <Pie
                  data={data}
                  dataKey="arc"
                  nameKey="key"
                  innerRadius={45}
                  outerRadius={70}
                  strokeWidth={1}
                  isAnimationActive={false}
                >
                  {data.map((entry, index) => (
                    <Cell
                      key={entry.key}
                      fill={CHART_COLORS[index % CHART_COLORS.length]}
                    />
                  ))}
                </Pie>
              </PieChart>
            ) : null}
            <ul className="w-full flex-1 space-y-1">
              {rows.map((row, index) => (
                <li
                  key={row.key}
                  className="flex items-center justify-between gap-3 text-sm"
                >
                  <span className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className="inline-block h-2.5 w-2.5 rounded-sm"
                      style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }}
                    />
                    <span className="font-medium">{row.key}</span>
                  </span>
                  <span className="flex items-center gap-3 tabular-nums">
                    <span className="text-muted-foreground">
                      {formatMoney(row.market_value, currency)}
                    </span>
                    <span className="w-16 text-right font-medium">
                      {formatPercent(row.weight)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Side-by-side sector and industry donuts fed from analytics allocations. */
export function AllocationCharts({
  currency,
  bySector,
  byIndustry,
}: {
  currency: string;
  bySector: AllocationWeight[];
  byIndustry: AllocationWeight[];
}) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <AllocationChart title="Allocation by sector" rows={bySector} currency={currency} />
      <AllocationChart
        title="Allocation by industry"
        rows={byIndustry}
        currency={currency}
      />
    </div>
  );
}
