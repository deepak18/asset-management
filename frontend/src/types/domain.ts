import type { components } from "@/types/api";

/**
 * Friendly aliases over the auto-generated OpenAPI schemas.
 *
 * Components import these names instead of reaching into `components["schemas"]`
 * everywhere, so the contract stays the single source of truth (regenerate
 * `api.ts` from `backend/openapi.json` and every consumer updates in lock-step),
 * while call sites read cleanly.
 *
 * Note the backend now emits `Transaction` as two schemas: `Transaction-Output`
 * (what reads return — every numeric field is a Decimal STRING) and
 * `Transaction-Input` (what POST bodies accept — numbers or strings). `Transaction`
 * below aliases the Output/read shape used across the ledger UI; `TransactionInput`
 * is the write shape used by the manual-entry form.
 */
export type PortfolioSummary = components["schemas"]["PortfolioSummary"];
export type Transaction = components["schemas"]["TransactionRecord"];
export type TransactionInput = components["schemas"]["Transaction"];
export type HoldingHistoryGap = components["schemas"]["HoldingHistoryGap"];
export type TransactionType = components["schemas"]["TransactionType"];
export type HoldingInfo = components["schemas"]["HoldingInfo"];
export type PortfolioAnalytics = components["schemas"]["PortfolioAnalytics"];

// Holding-level (per-ticker) money-weighted return surface.
//
// `HoldingReturnStatus` is why this holding's XIRR is (or is not) a number. Like
// the portfolio-level status, a bare `null` could not tell "snapshot-only history"
// from "we could not price this open position" — distinct problems with distinct
// fixes — so the reason travels with the value and the UI explains it rather than
// printing a misleading 0. `valuation_*` records how the terminal value was dated
// and sourced (quote provenance for open positions, the final ledger date for
// closed ones), surfaced only when the backend actually supplies it.
export type HoldingAnalytics = components["schemas"]["HoldingAnalytics"];
export type HoldingReturnStatus = components["schemas"]["HoldingReturnStatus"];
export type HoldingValuationSource = components["schemas"]["HoldingValuationSource"];
export type MarketDataProvenance = components["schemas"]["MarketDataProvenance"];
export type AllocationWeight = components["schemas"]["AllocationWeight"];
export type CostBasisResult = components["schemas"]["CostBasisResult"];
export type UnrealizedResult = components["schemas"]["UnrealizedResult"];
export type OpenLot = components["schemas"]["OpenLot"];

// Write + import surface (new in this contract revision).
export type PortfolioCreate = components["schemas"]["PortfolioCreate"];
export type PositionSnapshot = components["schemas"]["PositionSnapshot"];
export type LedgerIngestResult = components["schemas"]["LedgerIngestResult"];
export type StatementFormat = components["schemas"]["StatementFormat"];
export type ImportStatus = components["schemas"]["ImportStatus"];
export type StatementImportStatus = components["schemas"]["StatementImportStatus"];

// Classification + XIRR-status surface (new in this contract revision).
//
// `MoneyWeightedReturnStatus` is why XIRR is (or is not) a number. A bare `null`
// could not distinguish "too little history" from "we could not price your open
// positions", and those call for opposite user action — so the reason now travels
// with the value and the UI explains it rather than printing a misleading 0.
export type MoneyWeightedReturnStatus =
  components["schemas"]["MoneyWeightedReturnStatus"];
export type HoldingClassificationResult =
  components["schemas"]["HoldingClassificationResult"];
export type HoldingClassificationUpdate =
  components["schemas"]["HoldingClassificationUpdate"];
export type DataGap = components["schemas"]["DataGap"];
export type ClassificationFailure = components["schemas"]["ClassificationFailure"];

/**
 * Allocation bucket the backend groups holdings under when sector/industry is
 * unknown. Named once here so the chart, the editor, and the mocks can never
 * drift on the spelling.
 */
export const UNCLASSIFIED_KEY = "UNCLASSIFIED";
