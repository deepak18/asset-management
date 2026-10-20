import { describe, expect, it } from "vitest";
import { apiClient } from "@/lib/api-client";

describe("holding contract and mocks", () => {
  it("reads one holding and returns typed 404 errors for missing resources", async () => {
    expect(await apiClient.getHolding(3, "pltr")).toMatchObject({
      ticker: "PLTR",
      data_gaps: ["SECTOR", "INDUSTRY"],
    });
    await expect(apiClient.getHolding(3, "MISSING")).rejects.toMatchObject({
      status: 404,
    });
    await expect(apiClient.getHolding(404, "PLTR")).rejects.toMatchObject({
      status: 404,
    });
    await expect(
      apiClient.updateHoldingClassification(3, "MISSING", { sector: "Energy" }),
    ).rejects.toMatchObject({ status: 404 });
  });

  it("preserves omitted fields, clears explicit nulls, and protects manual edits", async () => {
    await apiClient.updateHoldingClassification(3, "PLTR", { sector: "Energy" });
    const first = await apiClient.classifyHoldings(3, { limit: 1 });
    expect(first.skipped).toContain("PLTR");
    expect(await apiClient.getHolding(3, "PLTR")).toMatchObject({
      sector: "Energy",
      industry: null,
      classification_source: "MANUAL",
    });
    expect((await apiClient.getAnalytics(3)).allocation_by_sector).toContainEqual({
      key: "Energy",
      market_value: "3000.00",
      weight: "0.3000",
    });
    await apiClient.updateHoldingClassification(3, "PLTR", { sector: null });
    const cleared = await apiClient.getHolding(3, "PLTR");
    expect(cleared.sector).toBeNull();
    expect(cleared.data_gaps).toContain("SECTOR");
    const refreshed = await apiClient.classifyHoldings(3, { refresh: true });
    expect(
      refreshed.classified.find((row) => row.ticker === "PLTR")?.classification_source,
    ).toBe("PROVIDER");
  });

  it("advances through unresolved tickers and rejects invalid requests", async () => {
    const first = await apiClient.classifyHoldings(3, { limit: 1 });
    expect(first.next_cursor).toBe("PLTR");
    const second = await apiClient.classifyHoldings(3, {
      limit: 1,
      afterTicker: first.next_cursor!,
    });
    expect(second.next_cursor).toBe("SOFI");
    expect(second.remaining).toBeLessThan(first.remaining);
    const third = await apiClient.classifyHoldings(3, {
      limit: 1,
      afterTicker: second.next_cursor!,
    });
    expect(third.remaining).toBe(0);
    expect(third.failures).toEqual([{ ticker: "ZZZZ", reason: "NO_PROFILE" }]);
    const fresh = await apiClient.classifyHoldings(3);
    expect(fresh.unresolved).toEqual(["ZZZZ"]);
    await expect(apiClient.classifyHoldings(3, { limit: 201 })).rejects.toMatchObject({
      status: 422,
    });
    await expect(
      apiClient.updateHoldingClassification(3, "PLTR", {}),
    ).rejects.toMatchObject({ status: 422 });
    await expect(
      apiClient.updateHoldingClassification(3, "PLTR", { sector: " " }),
    ).rejects.toMatchObject({ status: 422 });
  });
});
