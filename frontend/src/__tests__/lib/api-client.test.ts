import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { apiClient, ApiError } from "@/lib/api-client";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";

/**
 * These exercise the real client against the MSW mock layer (started in
 * vitest.setup.ts), proving the fetch/parse/error-translation path works
 * end-to-end without a live backend.
 *
 * NB: jsdom does not serialize `FormData` request bodies, so the import-upload
 * tests can't rely on the default handler reading the file; they override the
 * POST handler to return the exact status the client must translate. In a real
 * browser (dev mock mode) the default handler reads the file directly.
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

  it("lists portfolios for the picker", async () => {
    const list = await apiClient.listPortfolios();
    expect(list.length).toBeGreaterThan(0);
    expect(list[0]).toHaveProperty("base_currency");
  });

  it("creates a portfolio and returns its identity", async () => {
    const created = await apiClient.createPortfolio({ name: "New Book", base_currency: "USD" });
    expect(created).toMatchObject({ name: "New Book", base_currency: "USD" });
    expect(typeof created.id).toBe("number");
  });

  it("adds transactions, echoing an ingest result", async () => {
    const result = await apiClient.addTransactions(1, [
      { ticker: "nvda", type: "BUY", trade_date: "2024-01-02", currency: "USD", quantity: "1", price: "500", fees: "0", amount: "0", split_ratio: "1" },
    ]);
    expect(result).toMatchObject({ portfolio_id: 1, created_transactions: 1 });
    expect(result.tickers).toContain("NVDA");
  });

  it("adds positions, echoing an ingest result", async () => {
    const result = await apiClient.addPositions(1, [
      { ticker: "AAPL", quantity: "10", currency: "USD", cost_basis_per_share: "150" },
    ]);
    expect(result).toMatchObject({ portfolio_id: 1, created_transactions: 1 });
  });

  it("uploads an import (202) and polls it to SUCCEEDED", async () => {
    const file = new File(["Activity Date,..."], "history.csv", { type: "text/csv" });
    const job = await apiClient.createImport(1, file);
    expect(job.status).toBe("PENDING");
    expect(job.total_rows).toBeNull();

    // Each poll advances the mock job; a few steps reach the terminal state.
    let latest = await apiClient.getImport(1, job.id);
    for (let i = 0; i < 5 && latest.status !== "SUCCEEDED"; i++) {
      latest = await apiClient.getImport(1, job.id);
    }
    expect(latest.status).toBe("SUCCEEDED");
    expect(latest.created_transactions).toBeGreaterThan(0);
    expect(latest.warnings.length).toBeGreaterThan(0);
  });

  it("rejects a duplicate upload with 409 unless allow_duplicate, surfacing the detail", async () => {
    server.use(
      http.post(`${env.apiBaseUrl}/api/v1/portfolios/1/imports`, ({ request }) => {
        const allow = new URL(request.url).searchParams.get("allow_duplicate") === "true";
        return allow
          ? HttpResponse.json({ status: "PENDING" }, { status: 202 })
          : HttpResponse.json({ detail: "Already imported." }, { status: 409 });
      }),
    );
    const dupe = new File(["x"], "duplicate.csv", { type: "text/csv" });
    await expect(apiClient.createImport(1, dupe)).rejects.toMatchObject({
      status: 409,
      detail: "Already imported.",
    });
    // The override succeeds when the duplicate guard is deliberately bypassed.
    const forced = await apiClient.createImport(1, dupe, { allowDuplicate: true });
    expect(forced.status).toBe("PENDING");
  });

  it("maps the 413 (too large) and 422 (unparseable) upload errors", async () => {
    server.use(
      http.post(`${env.apiBaseUrl}/api/v1/portfolios/1/imports`, () =>
        HttpResponse.json({ detail: "Too large." }, { status: 413 }),
      ),
    );
    const big = new File(["x"], "large-export.csv", { type: "text/csv" });
    await expect(apiClient.createImport(1, big)).rejects.toMatchObject({ status: 413 });

    server.use(
      http.post(`${env.apiBaseUrl}/api/v1/portfolios/1/imports`, () =>
        HttpResponse.json({ detail: "Unparseable." }, { status: 422 }),
      ),
    );
    const bad = new File(["x"], "bad.csv", { type: "text/csv" });
    await expect(apiClient.createImport(1, bad)).rejects.toMatchObject({ status: 422 });
  });
});
