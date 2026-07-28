import { PortfolioSummary } from "@/components/portfolio/portfolio-summary";
import { AllocationSection } from "@/components/portfolio/allocation-section";
import { TransactionLedger } from "@/components/portfolio/transaction-ledger";
import { Watchlist } from "@/components/portfolio/watchlist";

/**
 * Unified Portfolio Dashboard (§1.4). Composes the summary overview, allocation
 * donuts, transaction ledger, and watchlist for a single portfolio. The id is
 * fixed to 1 for now (single local user); routing to arbitrary portfolios is a
 * later enhancement once a portfolio picker lands.
 */
const PORTFOLIO_ID = 1;

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-6">
      <PortfolioSummary portfolioId={PORTFOLIO_ID} />
      <AllocationSection portfolioId={PORTFOLIO_ID} />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[2fr_1fr]">
        <TransactionLedger portfolioId={PORTFOLIO_ID} />
        <Watchlist />
      </div>
    </div>
  );
}
