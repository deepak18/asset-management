"use client";

import { AllocationCharts } from "@/components/portfolio/allocation-chart";
import { ErrorState, LoadingRows } from "@/components/shared/states";
import { usePortfolioAnalytics } from "@/hooks/use-portfolio";

/**
 * Data wrapper that feeds the allocation donuts from analytics. Splitting the
 * fetch out of the presentational {@link AllocationCharts} keeps that component
 * pure (easy to unit-test with fixed props) while this shell owns the async
 * loading/error handling.
 */
export function AllocationSection({ portfolioId }: { portfolioId: number }) {
  const state = usePortfolioAnalytics(portfolioId);

  if (state.status === "loading") {
    return <LoadingRows rows={3} />;
  }
  if (state.status === "error") {
    return <ErrorState message="Could not load allocation data." />;
  }
  return (
    <AllocationCharts
      currency={state.data.base_currency}
      bySector={state.data.allocation_by_sector}
      byIndustry={state.data.allocation_by_industry}
    />
  );
}
