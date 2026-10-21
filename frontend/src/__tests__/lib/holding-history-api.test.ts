import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { apiClient } from "@/lib/api-client";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { createImport, getHoldings } from "@/mocks/state";

const base = `${env.apiBaseUrl}/api/v1/portfolios`;
const cash = {
  ticker: "AAPL",
  type: "DIVIDEND" as const,
  currency: "USD",
  trade_date: "2024-06-01",
  amount: "2.123456789",
  quantity: "0",
  price: "0",
  fees: "0",
  split_ratio: "1",
};

it("GET/POST use exact scoped, encoded paths and preserve ticker case and strict payload", async () => {
  const snapshot = await apiClient.getHoldingHistory(1, "aapl");
  expect(snapshot.ticker).toBe("AAPL");
  expect(
    snapshot.transactions.every(
      (row) => row.portfolio_id === 1 && row.ticker === "AAPL",
    ),
  ).toBe(true);
  expect(typeof snapshot.transactions[0]!.quantity).toBe("string");
  server.use(
    http.get(`${base}/7/holdings/:ticker/history`, ({ request }) => {
      expect(new URL(request.url).pathname).toBe(
        "/api/v1/portfolios/7/holdings/a%2Fb%20c/history",
      );
      return HttpResponse.json(snapshot);
    }),
    http.post(`${base}/7/holdings/:ticker/history`, async ({ request }) => {
      expect(new URL(request.url).pathname).toBe(
        "/api/v1/portfolios/7/holdings/a%2Fb%20c/history",
      );
      expect(await request.json()).toEqual({
        review_token: snapshot.review_token,
        confirmed: true,
      });
      return HttpResponse.json(snapshot);
    }),
  );
  await apiClient.getHoldingHistory(7, "a/b c");
  await apiClient.confirmHoldingHistory(7, "a/b c", {
    review_token: snapshot.review_token,
    confirmed: true,
  });
});

it("confirmation is durable and stable but additions invalidate only the affected holding", async () => {
  const first = await apiClient.getHoldingHistory(1, "AAPL");
  expect(first.confirmed_at).toBeNull();
  const confirmed = await apiClient.confirmHoldingHistory(1, "aapl", {
    review_token: first.review_token,
    confirmed: true,
  });
  expect(confirmed.history_complete).toBe(true);
  expect(confirmed.confirmed_at).toBeTruthy();
  expect(
    await apiClient.confirmHoldingHistory(1, "AAPL", {
      review_token: first.review_token,
      confirmed: true,
    }),
  ).toEqual(confirmed);
  await apiClient.addTransactions(1, [{ ...cash, ticker: "MSFT" }]);
  expect((await apiClient.getHoldingHistory(1, "AAPL")).confirmed_at).toBe(
    confirmed.confirmed_at,
  );
  await apiClient.addTransactions(1, [cash]);
  const changed = await apiClient.getHoldingHistory(1, "AAPL");
  expect(changed.confirmed_at).toBeNull();
  expect(changed.history_gaps).toContain("HISTORY_CHANGED");
  expect(changed.transactions.at(-1)!.amount).toBe("2.123456789");
  await expect(
    apiClient.confirmHoldingHistory(1, "AAPL", {
      review_token: first.review_token,
      confirmed: true,
    }),
  ).rejects.toMatchObject({ status: 409 });
});

it("deletion invalidates saved confirmation and import state makes old snapshots stale", async () => {
  const review = await apiClient.getHoldingHistory(1, "AAPL");
  await apiClient.confirmHoldingHistory(1, "AAPL", {
    review_token: review.review_token,
    confirmed: true,
  });
  await apiClient.deleteTransaction(1, 103);
  const changed = await apiClient.getHoldingHistory(1, "AAPL");
  expect(changed.history_gaps).toEqual(
    expect.arrayContaining(["HISTORY_CHANGED", "DELETED_TRANSACTION"]),
  );
  expect(changed.transactions.some((row) => row.id === 103)).toBe(false);
  createImport(1, "history.csv", 200, false);
  await expect(
    apiClient.confirmHoldingHistory(1, "AAPL", {
      review_token: changed.review_token,
      confirmed: true,
    }),
  ).rejects.toMatchObject({ status: 409 });
  expect((await apiClient.getHoldingHistory(1, "AAPL")).blocking_gaps).toContain(
    "IMPORT_NOT_SUCCEEDED",
  );
});

it("refuses blockers even with valid acknowledgement and a current token", async () => {
  const holding = getHoldings(1)![0]!;
  holding.history_complete = false;
  holding.history_gaps = ["SNAPSHOT", "INVALID_LEDGER"];
  const review = await apiClient.getHoldingHistory(1, holding.ticker);
  await expect(
    apiClient.confirmHoldingHistory(1, holding.ticker, {
      review_token: review.review_token,
      confirmed: true,
    }),
  ).rejects.toMatchObject({ status: 409 });
});

it.each([0, "true", false, null, undefined])(
  "strictly rejects acknowledgement %s",
  async (confirmed) => {
    const review = await apiClient.getHoldingHistory(1, "AAPL");
    const response = await fetch(`${base}/1/holdings/AAPL/history`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_token: review.review_token, confirmed }),
    });
    expect(response.status).toBe(422);
  },
);

describe("absent and cross-scope holdings", () => {
  it.each([
    [999, "AAPL"],
    [1, "ABSENT"],
  ])("returns 404 for %s/%s", async (id, ticker) => {
    await expect(
      apiClient.getHoldingHistory(id as number, ticker as string),
    ).rejects.toMatchObject({ status: 404 });
    await expect(
      apiClient.confirmHoldingHistory(id as number, ticker as string, {
        review_token: "bad",
        confirmed: true,
      }),
    ).rejects.toMatchObject({ status: 404 });
  });
  it("cannot use another holding or portfolio token", async () => {
    const review = await apiClient.getHoldingHistory(1, "AAPL");
    await expect(
      apiClient.confirmHoldingHistory(1, "MSFT", {
        review_token: review.review_token,
        confirmed: true,
      }),
    ).rejects.toMatchObject({ status: 409 });
    await expect(
      apiClient.confirmHoldingHistory(2, "AAPL", {
        review_token: review.review_token,
        confirmed: true,
      }),
    ).rejects.toMatchObject({ status: 409 });
  });
});
