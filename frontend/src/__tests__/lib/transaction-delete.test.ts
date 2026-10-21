import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { apiClient, ApiError } from "@/lib/api-client";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";

const base = `${env.apiBaseUrl}/api/v1/portfolios`;

describe("stable ledger identity and deletion", () => {
  it("keeps read IDs distinct from write inputs and returns a bodyless 204", async () => {
    const rows = await apiClient.listTransactions(1);
    expect(rows[0]).toMatchObject({ id: 101, portfolio_id: 1, quantity: "10" });
    await expect(apiClient.addTransactions(1, [{ ...rows[0]! }])).rejects.toMatchObject(
      { status: 422 },
    );
    await expect(apiClient.deleteTransaction(1, 102)).resolves.toBeUndefined();
    expect((await apiClient.listTransactions(1)).some((row) => row.id === 102)).toBe(
      false,
    );
    const analytics = await apiClient.getAnalytics(1);
    expect(analytics.positions.map((row) => row.ticker)).toEqual(["AAPL"]);
    expect(analytics.allocation_by_ticker.map((row) => row.key)).toEqual(["AAPL"]);
    expect(analytics.market_value_base).toBe("1290.00");
    expect(await apiClient.getHolding(1, "MSFT")).toMatchObject({
      history_complete: false,
      history_gaps: ["DELETED_TRANSACTION", "NO_TRANSACTIONS"],
    });
    await expect(apiClient.deleteTransaction(1, 102)).rejects.toMatchObject({
      status: 404,
    });
    await expect(apiClient.deleteTransaction(2, 101)).rejects.toMatchObject({
      status: 404,
    });
  });

  it("surfaces dependent-sale and active-import conflicts without deleting the row", async () => {
    await expect(apiClient.deleteTransaction(1, 101)).rejects.toMatchObject({
      status: 409,
      detail: expect.stringMatching(/sale/),
    });
    expect((await apiClient.listTransactions(1)).some((row) => row.id === 101)).toBe(
      true,
    );
    await apiClient.createImport(1, new File(["a"], "file.csv"));
    await expect(apiClient.deleteTransaction(1, 102)).rejects.toMatchObject({
      status: 409,
      detail: expect.stringMatching(/import/),
    });
    expect((await apiClient.listTransactions(1)).some((row) => row.id === 102)).toBe(
      true,
    );
  });

  it("uses the scoped URL and maps server/network errors without parsing success JSON", async () => {
    const seen: string[] = [];
    server.use(
      http.delete(`${base}/1/transactions/103`, ({ request }) => {
        seen.push(request.url);
        return HttpResponse.json({ detail: "Service unavailable" }, { status: 503 });
      }),
    );
    await expect(apiClient.deleteTransaction(1, 103)).rejects.toMatchObject({
      status: 503,
      detail: "Service unavailable",
    });
    expect(seen).toEqual([`${base}/1/transactions/103`]);
    server.use(http.delete(`${base}/1/transactions/103`, () => HttpResponse.error()));
    await expect(apiClient.deleteTransaction(1, 103)).rejects.toBeInstanceOf(Error);
    expect(new ApiError(404, "url", "missing").status).toBe(404);
  });
});

describe("import retry and history diagnostics", () => {
  it("preserves import audit facts but invalidates retry after editing its ledger", async () => {
    const job = await apiClient.createImport(1, new File(["csv"], "activity.csv"));
    await apiClient.getImport(1, job.id);
    await apiClient.getImport(1, job.id);
    await apiClient.getImport(1, job.id);
    await apiClient.deleteTransaction(1, 103);
    const after = (await apiClient.listImports(1))[0]!;
    expect(after.status).toBe("SUCCEEDED");
    expect(after.created_transactions).toBe(3);
    expect(after.retry_safe).toBe(false);
    expect(await apiClient.getHolding(1, "AAPL")).toMatchObject({
      history_complete: false,
    });
    expect(
      (await apiClient.getHoldingAnalytics(1, "AAPL")).money_weighted_return,
    ).toBeNull();
  });
});
