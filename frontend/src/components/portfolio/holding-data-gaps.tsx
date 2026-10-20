import { TriangleAlert } from "lucide-react";
import type { DataGap } from "@/types/domain";

const LABELS: Record<DataGap, string> = {
  SECTOR: "Sector missing",
  INDUSTRY: "Industry missing",
  COST_BASIS: "Cost basis needs attention",
  CURRENCY: "Currency missing",
  SPLIT_RATIO: "Split ratio needs attention",
  TICKER: "Ticker missing",
  TRADE_DATE: "Trade date missing",
  QUANTITY: "Quantity needs attention",
  TRANSACTION: "Transaction needs attention",
};

export function HoldingDataGaps({ gaps }: { gaps: DataGap[] }) {
  if (!gaps.length)
    return <span className="text-sm text-muted-foreground">No reported gaps</span>;
  return (
    <div className="flex items-start gap-2 text-sm">
      <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden />
      <div>
        <span className="sr-only">Needs attention: </span>
        <ul>
          {[...new Set(gaps)].map((gap) => (
            <li key={gap}>{LABELS[gap]}</li>
          ))}
        </ul>
        {gaps.some((gap) => gap !== "SECTOR" && gap !== "INDUSTRY") ? (
          <p className="text-muted-foreground">
            Review your source statement and ledger history; classification edits do not
            repair these items.
          </p>
        ) : null}
      </div>
    </div>
  );
}
