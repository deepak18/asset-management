import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { HoldingDetail } from "@/components/portfolio/holding-detail";
import { TransactionLedger } from "@/components/portfolio/transaction-ledger";
import { apiClient } from "@/lib/api-client";
import { env } from "@/lib/env";
import { addMockTransactions, getTransactions } from "@/mocks/state";
import type { LedgerOrigin } from "@/types/domain";

const origins: [LedgerOrigin, string][] = [
  ["OBSERVED", "Observed event"],
  ["SNAPSHOT", "Synthetic snapshot"],
  ["UNKNOWN", "Legacy / unverified"],
];
const actual = {
  ticker: "MSFT",
  type: "BUY" as const,
  trade_date: "2024-01-01",
  currency: "USD",
  quantity: "2",
  price: "123.123456789",
  fees: "0",
  amount: "0",
  split_ratio: "1",
};

it("shows mixed origins beside the correct stable IDs in review and the detail ledger", async () => {
  for (const [origin] of origins) addMockTransactions(1, [actual], origin);
  const rows = getTransactions(1)!.slice(-3);
  render(<HoldingDetail portfolioId={1} ticker="MSFT" />);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", { name: "Review History For MSFT" }),
  );
  const review = screen.getByRole("dialog");
  await within(review).findByRole("table");
  expect(
    within(review).getByRole("columnheader", { name: "Origin" }),
  ).toBeInTheDocument();
  for (const [index, row] of rows.entries()) {
    const reviewRow = within(review)
      .getByRole("cell", { name: String(row.id) })
      .closest("tr")!;
    expect(within(reviewRow).getByText(origins[index]![1])).toBeInTheDocument();
    expect(within(reviewRow).getByText("123.123456789")).toBeInTheDocument();
    const ledgerRow = document.querySelector(
      `#holding-ledger [data-transaction-id="${row.id}"]`,
    )!;
    expect(
      within(ledgerRow as HTMLElement).getByText(origins[index]![1]),
    ).toBeInTheDocument();
    expect(
      within(ledgerRow as HTMLElement).getByRole("button", {
        name: `Delete MSFT BUY Transaction ${row.id}`,
      }),
    ).toBeInTheDocument();
  }
  expect(within(review).getByRole("checkbox")).toBeDisabled();
  expect(within(review).queryByText(/History complete under/)).toBeNull();
});

it.each(origins)(
  "deletion confirmation names the selected %s origin and ID",
  async (origin, label) => {
    addMockTransactions(1, [actual], origin);
    const row = getTransactions(1)!.at(-1)!;
    const user = userEvent.setup();
    render(<TransactionLedger portfolioId={1} />);
    expect(
      await screen.findByRole("columnheader", { name: "Origin" }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: `Delete MSFT BUY Transaction ${row.id}` }),
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(`Transaction ${row.id}: ${label}.`);
    expect(dialog).toHaveTextContent("MSFT BUY on 2024-01-01");
    expect(dialog).toHaveTextContent("portfolio 1");
    for (const [, other] of origins)
      if (other !== label) expect(dialog).not.toHaveTextContent(other);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(getTransactions(1)).toContainEqual(row);
  },
);

it("derives scoped snapshot/legacy diagnostics and changes the mock token when origin changes", async () => {
  const first = await apiClient.getHoldingHistory(1, "MSFT");
  const row = getTransactions(1)!.find((event) => event.id === 102)!;
  row.history_origin = "UNKNOWN";
  const legacy = await apiClient.getHoldingHistory(1, "MSFT");
  expect(legacy.history_gaps).toContain("UNKNOWN_ORIGIN");
  expect(legacy.review_token).not.toBe(first.review_token);
  expect((await apiClient.getHolding(1, "MSFT")).history_complete).toBe(false);
  await expect(
    apiClient.confirmHoldingHistory(1, "MSFT", {
      confirmed: true,
      review_token: first.review_token,
    }),
  ).rejects.toMatchObject({ status: 409 });
  const confirmed = await apiClient.confirmHoldingHistory(1, "MSFT", {
    confirmed: true,
    review_token: legacy.review_token,
  });
  expect(confirmed.history_complete).toBe(true);
  expect(confirmed.transactions[0]!.history_origin).toBe("UNKNOWN");
  expect((await apiClient.getHolding(1, "MSFT")).history_complete).toBe(true);
  row.history_origin = "SNAPSHOT";
  const synthetic = await apiClient.getHoldingHistory(1, "MSFT");
  expect(synthetic.confirmed_at).toBeNull();
  expect(synthetic.blocking_gaps).toContain("SNAPSHOT");
  expect(
    (await apiClient.getAnalytics(1)).positions.find(
      (position) => position.ticker === "MSFT",
    )!.history_gaps,
  ).toContain("SNAPSHOT");
  expect((await apiClient.getHoldingHistory(1, "AAPL")).history_gaps).toEqual([]);
});

it.each(["history_origin", "id", "portfolio_id"])(
  "strict write contract rejects read-only %s",
  async (field) => {
    const response = await fetch(`${env.apiBaseUrl}/api/v1/portfolios/1/transactions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify([
        { ...actual, [field]: field === "history_origin" ? "OBSERVED" : 1 },
      ]),
    });
    expect(response.status).toBe(422);
    const count = (await apiClient.listTransactions(1)).length;
    await apiClient.addTransactions(1, [actual]);
    const rows = await apiClient.listTransactions(1);
    expect(rows).toHaveLength(count + 1);
    expect(rows.at(-1)).toMatchObject({ ...actual, history_origin: "OBSERVED" });
  },
);

it("seeded add-position, imported and legacy rows retain their actual provenance", async () => {
  const rows = await apiClient.listTransactions(3);
  expect(
    rows.map(({ id, ticker, history_origin }) => ({ id, ticker, history_origin })),
  ).toEqual([
    { id: 301, ticker: "NVDA", history_origin: "SNAPSHOT" },
    { id: 302, ticker: "PLTR", history_origin: "OBSERVED" },
    { id: 303, ticker: "SOFI", history_origin: "OBSERVED" },
    { id: 304, ticker: "ZZZZ", history_origin: "UNKNOWN" },
  ]);
  expect((await apiClient.getHoldingHistory(3, "NVDA")).blocking_gaps).toContain(
    "SNAPSHOT",
  );
  expect((await apiClient.getHoldingHistory(3, "ZZZZ")).history_gaps).toContain(
    "UNKNOWN_ORIGIN",
  );
});
