"use client";

import { AllocationCharts } from "@/components/portfolio/allocation-chart";
import { ErrorState, LoadingRows } from "@/components/shared/states";
import { useHoldings, usePortfolioAnalytics } from "@/hooks/use-portfolio";

/**
 * Data wrapper that feeds the allocation donuts from analytics. Splitting the
 * fetch out of the presentational {@link AllocationCharts} keeps that component
 * pure (easy to unit-test with fixed props) while this shell owns the async
 * loading/error handling.
 */
export function AllocationSection({
  portfolioId,
  refreshToken = 0,
}: {
  portfolioId: number;
  refreshToken?: number;
}) {
  return (
    <ScopedAllocationSection
      key={`${portfolioId}:${refreshToken}`}
      portfolioId={portfolioId}
      refreshToken={refreshToken}
    />
  );
}

function ScopedAllocationSection({
  portfolioId,
  refreshToken,
}: {
  portfolioId: number;
  refreshToken: number;
}) {
  // Remount both resources for every scope/version. The shared hook keeps its
  // previous result until its effect runs; a key prevents mixed-generation data.
  const state = usePortfolioAnalytics(portfolioId, refreshToken);
  const holdings = useHoldings(portfolioId, refreshToken);

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
      breakdown={{ holdings, analytics: state.data }}
    />
  );
}
