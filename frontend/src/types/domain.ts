import type { components } from "@/types/api";

/**
 * Friendly aliases over the auto-generated OpenAPI schemas.
 *
 * Components import these names instead of reaching into `components["schemas"]`
 * everywhere, so the contract stays the single source of truth (regenerate
 * `api.ts` from `backend/openapi.json` and every consumer updates in lock-step),
 * while call sites read cleanly.
 *
 * Ledger reads use TransactionRecord (stable identity and Decimal strings).
 * TransactionInput aliases the distinct Transaction request schema, whose
 * decimal fields accept numbers or strings. Inputs never send read-only IDs.
 */
export type PortfolioSummary = components["schemas"]["PortfolioSummary"];
export type Transaction = components["schemas"]["TransactionRecord"];
export type TransactionInput = components["schemas"]["Transaction"];
export type LedgerOrigin = components["schemas"]["LedgerOrigin"];
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
// Generated defaults are required in TS; HTTP inputs may omit defaulted account_type.
type PortfolioCreateSchema = components["schemas"]["PortfolioCreate"];
export type PortfolioCreate = Omit<PortfolioCreateSchema, "account_type"> &
  Partial<Pick<PortfolioCreateSchema, "account_type">>;
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

// Review + confirmation request surface (new in this contract revision).
export type HoldingHistoryReview = components["schemas"]["HoldingHistoryReview"];
export type HoldingHistoryConfirmation =
  components["schemas"]["HoldingHistoryConfirmation"];

/**
 * Allocation bucket the backend groups holdings under when sector/industry is
 * unknown. Named once here so the chart, the editor, and the mocks can never
 * drift on the spelling.
 */
export const UNCLASSIFIED_KEY = "UNCLASSIFIED";

// Named aliases for the published account, valuation and retirement request/read schemas.
export type AccountType = components["schemas"]["AccountType"];
type AccountUpdateSchema = components["schemas"]["AccountUpdate"];
export type AccountUpdate = Omit<AccountUpdateSchema, "account_type"> &
  Partial<Pick<AccountUpdateSchema, "account_type">>;
export type SecurityInfo = components["schemas"]["SecurityInfo"];
export type ValuationView = components["schemas"]["ValuationView"];
export type RetirementOptions = components["schemas"]["ImportOptions"];
export type RetirementPreview = components["schemas"]["RetirementPreview"];
export type RetirementImport = components["schemas"]["RetirementImport"];
export type ObservedActivity = components["schemas"]["ObservedActivity"];
export type ActivityFact = components["schemas"]["ActivityFact"];
