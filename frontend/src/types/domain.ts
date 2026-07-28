import type { components } from "@/types/api";

/**
 * Friendly aliases over the auto-generated OpenAPI schemas.
 *
 * Components import these names instead of reaching into `components["schemas"]`
 * everywhere, so the contract stays the single source of truth (regenerate
 * `api.ts` from `backend/openapi.json` and every consumer updates in lock-step),
 * while call sites read cleanly.
 */
export type PortfolioSummary = components["schemas"]["PortfolioSummary"];
export type Transaction = components["schemas"]["Transaction"];
export type TransactionType = components["schemas"]["TransactionType"];
export type HoldingInfo = components["schemas"]["HoldingInfo"];
export type PortfolioAnalytics = components["schemas"]["PortfolioAnalytics"];
export type AllocationWeight = components["schemas"]["AllocationWeight"];
export type CostBasisResult = components["schemas"]["CostBasisResult"];
export type UnrealizedResult = components["schemas"]["UnrealizedResult"];
export type OpenLot = components["schemas"]["OpenLot"];
