"use client";

import * as React from "react";
import Link from "next/link";
import { apiClient } from "@/lib/api-client";
import { usePortfolioAnalytics } from "@/hooks/use-portfolio";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingRows } from "@/components/shared/states";
import { HoldingClassificationCell } from "./holding-classification-cell";
import { HoldingDataGaps } from "./holding-data-gaps";
import { ClassifyHoldingsButton } from "./classify-holdings-button";
import { HoldingHistory } from "./holding-history";
import { HoldingHistoryReviewAction } from "./holding-history-review";
import { formatMoney, formatQuantity } from "@/lib/format";
import type { HoldingInfo } from "@/types/domain";
import { classificationSuggestions } from "./classification-combobox";

export function HoldingsTable(props: {
  portfolioId: number;
  refreshToken?: number;
  onChanged?: () => void;
}) {
  return <HoldingsForPortfolio key={props.portfolioId} {...props} />;
}

function HoldingsForPortfolio({
  portfolioId,
  refreshToken = 0,
  onChanged,
}: {
  portfolioId: number;
  refreshToken?: number;
  onChanged?: () => void;
}) {
  const [holdings, setHoldings] = React.useState<HoldingInfo[] | null>(null);
  const [error, setError] = React.useState(false);
  const [version, setVersion] = React.useState(0);
  const analytics = usePortfolioAnalytics(portfolioId, refreshToken + version);
  const suggestions = React.useMemo(
    () => classificationSuggestions(holdings ?? []),
    [holdings],
  );

  // Keep mounted cells during refresh so saving one field never discards another draft.
  React.useEffect(() => {
    let active = true;
    apiClient
      .listHoldings(portfolioId)
      .then((rows) => {
        if (active) {
          setHoldings(rows);
          setError(false);
        }
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, [portfolioId, refreshToken, version]);

  function changed() {
    setVersion((value) => value + 1);
    onChanged?.();
  }
  const data = analytics.status === "success" ? analytics.data : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Holdings</CardTitle>
        <ClassifyHoldingsButton portfolioId={portfolioId} onChanged={changed} />
      </CardHeader>
      <CardContent>
        {error ? (
          <ErrorState message="Could not refresh holdings. Displayed labels may be out of date." />
        ) : null}
        {holdings == null ? (
          !error ? (
            <LoadingRows rows={3} />
          ) : null
        ) : holdings.length === 0 ? (
          <EmptyState message="No holdings yet. Add a position or import your history." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                {[
                  "Ticker",
                  "Quantity",
                  "Cost basis",
                  "Market value",
                  "Sector",
                  "Industry",
                  "Data quality",
                ].map((label) => (
                  <TableHead key={label}>{label}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {holdings.map((holding) => {
                const position = data?.positions.find(
                  (row) => row.ticker === holding.ticker,
                );
                const valuation = data?.positions_unrealized.find(
                  (row) => row.ticker === holding.ticker,
                );
                return (
                  <TableRow key={holding.ticker}>
                    <TableCell>
                      <Link
                        className="font-medium underline"
                        href={`/portfolios/${portfolioId}/holdings/${encodeURIComponent(holding.ticker)}`}
                      >
                        {holding.ticker}
                      </Link>
                    </TableCell>
                    <TableCell>{formatQuantity(position?.open_quantity)}</TableCell>
                    <TableCell>
                      {formatMoney(
                        position?.open_cost_basis_base,
                        data?.base_currency ?? "",
                      )}
                    </TableCell>
                    <TableCell>
                      {formatMoney(
                        valuation?.market_value_base ??
                          data?.allocation_by_ticker.find(
                            (row) => row.key === holding.ticker,
                          )?.market_value,
                        data?.base_currency ?? "",
                      )}
                    </TableCell>
                    <TableCell>
                      <HoldingClassificationCell
                        portfolioId={portfolioId}
                        holding={holding}
                        field="sector"
                        suggestions={suggestions.sector}
                        onChanged={changed}
                      />
                    </TableCell>
                    <TableCell>
                      <HoldingClassificationCell
                        portfolioId={portfolioId}
                        holding={holding}
                        field="industry"
                        suggestions={suggestions.industry}
                        onChanged={changed}
                      />
                    </TableCell>
                    <TableCell>
                      <HoldingHistory holding={holding} />
                      <HoldingHistoryReviewAction
                        portfolioId={portfolioId}
                        ticker={holding.ticker}
                        refreshToken={refreshToken + version}
                        onChanged={changed}
                      />
                      <HoldingDataGaps
                        gaps={[...holding.data_gaps, ...(position?.data_gaps ?? [])]}
                      />
                      {data?.unpriced_tickers.includes(holding.ticker) ? (
                        <p className="text-sm text-muted-foreground">
                          Price unavailable — connect market data or check provider
                          availability.
                        </p>
                      ) : null}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
        {analytics.status === "error" ? (
          <ErrorState message="Position values unavailable. Classification editing still works." />
        ) : null}
      </CardContent>
    </Card>
  );
}
