import { describe, expect, it } from "vitest";
import { apiClient, ApiError } from "@/lib/api-client";

/**
 * These exercise the real client against the MSW mock layer (started in
 * vitest.setup.ts), proving the fetch/parse/error-translation path works
 * end-to-end without a live backend.
 */
describe("apiClient", () => {
  it("fetches a portfolio summary shaped by the contract", async () => {
    const summary = await apiClient.getPortfolio(1);
    expect(summary).toMatchObject({ id: 1, base_currency: "USD" });
  });

  it("returns the ledger for a populated portfolio", async () => {
    const txns = await apiClient.listTransactions(1);
    expect(txns.length).toBeGreaterThan(0);
    expect(txns[0]).toHaveProperty("ticker");
  });

  it("returns analytics with Decimal values as strings", async () => {
    const analytics = await apiClient.getAnalytics(1);
    expect(typeof analytics.open_cost_basis_base).toBe("string");
    expect(analytics.base_currency).toBe("USD");
  });

  it("reports health", async () => {
    await expect(apiClient.health()).resolves.toMatchObject({ status: "ok" });
  });

  it("throws a typed ApiError with status for a missing portfolio", async () => {
    await expect(apiClient.getPortfolio(404)).rejects.toBeInstanceOf(ApiError);
    await expect(apiClient.getPortfolio(404)).rejects.toMatchObject({ status: 404 });
  });
});
