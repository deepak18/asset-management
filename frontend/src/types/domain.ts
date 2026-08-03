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
export type Transaction = components["schemas"]["Transaction-Output"];
export type TransactionInput = components["schemas"]["Transaction-Input"];
export type TransactionType = components["schemas"]["TransactionType"];
export type HoldingInfo = components["schemas"]["HoldingInfo"];
export type PortfolioAnalytics = components["schemas"]["PortfolioAnalytics"];
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
