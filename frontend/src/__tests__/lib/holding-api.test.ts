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

describe("holding analytics (per-ticker XIRR) contract and mocks", () => {
  it("scopes the return to the URL portfolio + ticker and encodes the path", async () => {
    const ok = await apiClient.getHoldingAnalytics(1, "aapl");
    expect(ok).toMatchObject({
      portfolio_id: 1,
      ticker: "AAPL",
      base_currency: "USD",
      money_weighted_return: "0.1842",
      money_weighted_return_status: "OK",
      valuation_source: "QUOTE",
    });
    expect(ok.valuation_provenance).toMatchObject({
      provider_code: "ALPHAVANTAGE",
      source_table: "GLOBAL_QUOTE",
    });
  });

  it("surfaces negative and zero returns as real OK figures", async () => {
    expect(await apiClient.getHoldingAnalytics(1, "MSFT")).toMatchObject({
      money_weighted_return: "-0.0530",
      money_weighted_return_status: "OK",
    });
    // Portfolio 2 is unpriced overall, yet a closed holding valued from the
    // ledger still returns a (zero) figure.
    expect(await apiClient.getHoldingAnalytics(2, "MSFT")).toMatchObject({
      money_weighted_return: "0",
      money_weighted_return_status: "OK",
      valuation_source: "LEDGER",
      valuation_provenance: null,
    });
  });

  it("is independent of unrelated holdings' missing prices or FX", async () => {
    // Same portfolio, different outcomes: AAPL priced/OK, XYZ withheld (MISSING_FX).
    const priced = await apiClient.getHoldingAnalytics(1, "AAPL");
    const withheld = await apiClient.getHoldingAnalytics(1, "XYZ");
    expect(priced.money_weighted_return_status).toBe("OK");
    expect(priced.money_weighted_return).toBe("0.1842");
    expect(withheld.money_weighted_return_status).toBe("MISSING_FX");
    expect(withheld.money_weighted_return).toBeNull();
    expect(withheld.valuation_source).toBe("UNAVAILABLE");
    expect(withheld.valuation_provenance).toBeNull();
  });

  it.each([
    ["2:AAPL", 2, "AAPL", "UNPRICED_POSITION"],
    ["3:NVDA", 3, "NVDA", "INCOMPLETE_HISTORY"],
    ["3:PLTR", 3, "PLTR", "INSUFFICIENT_FLOWS"],
    ["3:SOFI", 3, "SOFI", "INVALID_HISTORY"],
  ] as const)(
    "reports %s as a null return with status %s",
    async (_label, id, ticker, status) => {
      const result = await apiClient.getHoldingAnalytics(id, ticker);
      expect(result.money_weighted_return).toBeNull();
      expect(result.money_weighted_return_status).toBe(status);
      expect(result.valuation_source).toBe("UNAVAILABLE");
      expect(result.valuation_provenance).toBeNull();
    },
  );

  it("returns a typed 404 for an unknown portfolio or holding", async () => {
    await expect(apiClient.getHoldingAnalytics(404, "AAPL")).rejects.toMatchObject({
      status: 404,
    });
    await expect(apiClient.getHoldingAnalytics(1, "MISSING")).rejects.toMatchObject({
      status: 404,
    });
  });
});
