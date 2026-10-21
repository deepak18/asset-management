"use client";

import * as React from "react";
import { Cell, Pie, PieChart, Sector } from "recharts";
import type { PieSectorDataItem } from "recharts/types/polar/Pie";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/shared/states";
import { formatMoney, formatPercent } from "@/lib/format";
import { parseDecimal } from "@/lib/decimal";
import { cn } from "@/lib/utils";
import type { AllocationWeight } from "@/types/domain";

function renderActiveSector(props: PieSectorDataItem) {
  return (
    <Sector
      {...props}
      outerRadius={74}
      stroke="hsl(var(--foreground))"
      strokeWidth={2}
    />
  );
}

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
  const asNumber = Number(
    `${parsed.negative ? "-" : ""}${parsed.int}.${parsed.frac || "0"}`,
  );
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
  const detailId = React.useId();
  const helpId = React.useId();
  const legendRefs = React.useRef(new Map<string, HTMLButtonElement>());
  const [selection, setSelection] = React.useState<{
    rows: AllocationWeight[];
    pinned: string | null;
    hovered: string | null;
    focused: string | null;
  }>({ rows, pinned: null, hovered: null, focused: null });

  // Retain identity across reordered/refreshed rows, never a removed category.
  if (selection.rows !== rows) {
    const retain = (key: string | null) =>
      rows.some((row) => row.key === key) ? key : null;
    setSelection({
      rows,
      pinned: retain(selection.pinned),
      hovered: retain(selection.hovered),
      focused: retain(selection.focused),
    });
  }
  const activeKey = selection.hovered ?? selection.focused ?? selection.pinned;
  const activeIndex = data.findIndex((row) => row.key === activeKey);
  const activeRow = data[activeIndex];
  const preview = (kind: "hovered" | "focused", key: string | null) =>
    setSelection((current) => ({ ...current, [kind]: key }));
  const toggle = (key: string) =>
    setSelection((current) => ({
      ...current,
      pinned: current.pinned === key ? null : key,
      hovered: null,
      focused: null,
    }));
  const clear = (restoreFocus: boolean) => {
    if (restoreFocus) {
      const key = selection.pinned ?? activeKey;
      if (key) legendRefs.current.get(key)?.focus();
    }
    // Focus restoration must not immediately reinstate the preview.
    setSelection((current) => ({
      ...current,
      pinned: null,
      hovered: null,
      focused: null,
    }));
  };

  return (
    <Card
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          clear(false);
        }
      }}
    >
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <EmptyState message="Not priced — allocation unavailable." />
        ) : (
          <>
            <p id={helpId} className="sr-only">
              Hover or focus a category to preview. Select to pin or unpin. Escape
              clears selection.
            </p>
            <div className="flex flex-col items-center gap-4 sm:flex-row">
              {hasArc ? (
                <div className="shrink-0" aria-hidden="true">
                  <PieChart width={160} height={160}>
                    <Pie
                      data={data}
                      dataKey="arc"
                      nameKey="key"
                      innerRadius={45}
                      outerRadius={70}
                      stroke="hsl(var(--card))"
                      strokeWidth={1}
                      activeIndex={activeIndex >= 0 ? activeIndex : undefined}
                      activeShape={renderActiveSector}
                      rootTabIndex={-1}
                      isAnimationActive={false}
                      onMouseEnter={(_, index) =>
                        preview("hovered", data[index]?.key ?? null)
                      }
                      onMouseLeave={() => preview("hovered", null)}
                      onClick={(_, index) => {
                        const row = data[index];
                        if (row) toggle(row.key);
                      }}
                    >
                      {data.map((entry, index) => (
                        <Cell
                          key={entry.key}
                          fill={CHART_COLORS[index % CHART_COLORS.length]}
                          fillOpacity={activeRow && activeKey !== entry.key ? 0.75 : 1}
                          className="cursor-pointer transition-opacity duration-150 motion-reduce:transition-none"
                        />
                      ))}
                    </Pie>
                  </PieChart>
                </div>
              ) : null}
              <ul
                aria-label={`${title} categories`}
                className="min-w-0 w-full flex-1 space-y-1"
              >
                {rows.map((row, index) => (
                  <li key={row.key}>
                    <button
                      ref={(node) => {
                        if (node) legendRefs.current.set(row.key, node);
                        else legendRefs.current.delete(row.key);
                      }}
                      type="button"
                      aria-pressed={selection.pinned === row.key}
                      aria-describedby={
                        activeKey === row.key ? `${helpId} ${detailId}` : helpId
                      }
                      onMouseEnter={() => preview("hovered", row.key)}
                      onMouseLeave={() => preview("hovered", null)}
                      onFocus={() => preview("focused", row.key)}
                      onBlur={() => preview("focused", null)}
                      onClick={() => toggle(row.key)}
                      className={cn(
                        "flex min-h-11 w-full flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-md border border-transparent px-2 py-1.5 text-left text-sm transition-colors duration-150 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-reduce:transition-none",
                        activeKey === row.key &&
                          "border-border bg-accent text-accent-foreground",
                        selection.pinned === row.key && "border-foreground",
                      )}
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <span
                          aria-hidden="true"
                          className="h-2.5 w-2.5 shrink-0 rounded-sm"
                          style={{
                            backgroundColor: CHART_COLORS[index % CHART_COLORS.length],
                          }}
                        />
                        <span className="break-words font-medium">{row.key}</span>
                        {selection.pinned === row.key ? (
                          <span className="text-xs">Selected</span>
                        ) : null}
                      </span>
                      <span className="ml-auto flex items-center gap-3 tabular-nums">
                        <span className="text-muted-foreground">
                          {formatMoney(row.market_value, currency)}
                        </span>
                        <span className="w-16 text-right font-medium">
                          {formatPercent(row.weight)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div className="mt-4 flex min-h-20 flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-popover p-3 text-sm text-popover-foreground shadow-sm">
              <div id={detailId} className="min-w-0">
                {activeRow ? (
                  <>
                    <p className="break-words font-semibold">{activeRow.key}</p>
                    <p className="tabular-nums">
                      {formatMoney(activeRow.market_value, currency)} ·{" "}
                      {formatPercent(activeRow.weight)}
                    </p>
                    {activeRow.arc === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        No visible slice for this weight.
                      </p>
                    ) : null}
                  </>
                ) : (
                  <p className="text-muted-foreground">
                    Hover or focus to inspect. Select to pin.
                  </p>
                )}
              </div>
              <button
                type="button"
                disabled={!selection.pinned && !activeRow}
                onClick={() => clear(true)}
                className="shrink-0 rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              >
                Clear Selection
              </button>
            </div>
          </>
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
      <AllocationChart
        title="Allocation by sector"
        rows={bySector}
        currency={currency}
      />
      <AllocationChart
        title="Allocation by industry"
        rows={byIndustry}
        currency={currency}
      />
    </div>
  );
}
