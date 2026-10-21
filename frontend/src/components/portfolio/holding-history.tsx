import { Badge } from "@/components/ui/badge";
import type { HoldingHistoryGap, HoldingInfo } from "@/types/domain";

/** History is a backend policy diagnostic, not a claim about missing trades. */
const REASONS: Record<HoldingHistoryGap, string> = {
  UNKNOWN_ORIGIN: "Legacy transaction origin is unverified.",
  SNAPSHOT: "A synthetic opening position snapshot is present.",
  IMPORT_NOT_COMPLETE: "A relevant import was not confirmed complete.",
  IMPORT_NOT_SUCCEEDED: "A relevant import has not succeeded.",
  UNRESOLVED_EVENTS: "Relevant source events still need review.",
  DELETED_TRANSACTION: "A transaction was removed from the active ledger.",
  NO_TRANSACTIONS: "This tracked holding has no active transactions.",
  NO_ACQUISITION: "No acquisition can be established from active BUY events.",
};

export function HoldingHistory({ holding }: { holding: HoldingInfo }) {
  if (holding.history_complete) return null;
  return (
    <div
      className="space-y-1 text-sm"
      aria-label={`${holding.ticker} history not confirmed`}
    >
      <Badge variant="muted">History not confirmed</Badge>
      <ul className="list-disc pl-5 text-muted-foreground">
        {holding.history_gaps.map((reason) => (
          <li key={reason}>{REASONS[reason]}</li>
        ))}
      </ul>
    </div>
  );
}
