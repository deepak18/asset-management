import type { LedgerOrigin } from "@/types/domain";

/** Row provenance only; an observed event does not establish complete history. */
export const LEDGER_ORIGIN_LABELS: Record<LedgerOrigin, string> = {
  OBSERVED: "Observed event",
  SNAPSHOT: "Synthetic snapshot",
  UNKNOWN: "Legacy / unverified",
};
