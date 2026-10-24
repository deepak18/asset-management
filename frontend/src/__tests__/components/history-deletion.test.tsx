import "./router-state";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { TransactionLedger } from "@/components/portfolio/transaction-ledger";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { HoldingDetail } from "@/components/portfolio/holding-detail";
import { Dashboard } from "@/components/portfolio/dashboard";
import {
  PortfolioSelectionProvider,
  usePortfolioSelection,
} from "@/hooks/use-portfolio-selection";
import { getHoldings, getTransactions, deleteTransaction } from "@/mocks/state";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import type { HoldingHistoryGap } from "@/types/domain";

const base = `${env.apiBaseUrl}/api/v1/portfolios`;

it("shows all typed reasons inline, multiple at once, but no claim for complete history", async () => {
  const reasons: HoldingHistoryGap[] = [
    "UNKNOWN_ORIGIN",
    "SNAPSHOT",
    "IMPORT_NOT_COMPLETE",
    "IMPORT_NOT_SUCCEEDED",
    "UNRESOLVED_EVENTS",
    "DELETED_TRANSACTION",
    "NO_TRANSACTIONS",
    "NO_ACQUISITION",
  ];
  server.use(
    http.get(`${base}/3/holdings`, () => {
      const rows = getHoldings(1)!;
      return HttpResponse.json([
        { ...rows[0], ticker: "TEST", history_complete: false, history_gaps: reasons },
      ]);
    }),
  );
  render(<HoldingsTable portfolioId={3} />);
  const row = (await screen.findByRole("link", { name: "TEST" })).closest("tr")!;
  const text = within(row);
  expect(text.getByText("History not confirmed")).toBeInTheDocument();
  for (const fragment of [
    "Legacy transaction",
    "synthetic opening",
    "not confirmed complete",
    "has not succeeded",
    "source events",
    "removed from",
    "no active transactions",
    "No acquisition",
  ]) {
    expect(text.getByText(new RegExp(fragment, "i"))).toBeInTheDocument();
  }
  expect(text.queryByText(/definitely missing/i)).toBeNull();
});

describe("ledger confirmation", () => {
  it("supports keyboard Escape, Cancel and dismiss without DELETE", async () => {
    const user = userEvent.setup();
    const requests = vi.fn();
    server.use(
      http.delete(`${base}/1/transactions/:id`, () => {
        requests();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<TransactionLedger portfolioId={1} />);
    await user.click(
      await screen.findByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
    );
    const dialog = screen.getByRole("dialog", { name: "Delete transaction?" });
    expect(dialog).toHaveTextContent(/MSFT BUY on 2024-02-01/);
    expect(dialog).toHaveTextContent(/retry safety/);
    expect(within(dialog).getByRole("button", { name: "Close Dialog" })).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(
      within(dialog).getByRole("button", { name: "Delete Transaction" }),
    ).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(
      screen.getByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
    );
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(requests).not.toHaveBeenCalled();
  });

  it("holds the row during pending, rejects double submission, and removes only the stable ID on success", async () => {
    const user = userEvent.setup();
    let finish!: () => void;
    const sent = vi.fn();
    server.use(
      http.delete(`${base}/1/transactions/102`, async () => {
        sent();
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        deleteTransaction(1, 102);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const changed = vi.fn();
    render(<TransactionLedger portfolioId={1} onDeleted={changed} />);
    await user.click(
      await screen.findByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
    );
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Delete Transaction",
      }),
    );
    expect(screen.getByRole("button", { name: "Deleting…" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
    ).toBeInTheDocument();
    expect(sent).toHaveBeenCalledTimes(1);
    finish();
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  });

  it("keeps the row and backend explanation for 409; refreshes stale 404", async () => {
    const user = userEvent.setup();
    render(<TransactionLedger portfolioId={1} />);
    await user.click(
      await screen.findByRole("button", { name: /Delete AAPL BUY Transaction 101/ }),
    );
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Delete Transaction",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /sale without enough shares/,
    );
    expect(
      screen.getByRole("button", { name: /Delete AAPL BUY Transaction 101/ }),
    ).toBeInTheDocument();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );
    server.use(
      http.delete(`${base}/1/transactions/103`, () =>
        HttpResponse.json({ detail: "missing" }, { status: 404 }),
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /Delete AAPL DIVIDEND Transaction 103/ }),
    );
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Delete Transaction",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/no longer exists/);
  });

  it("drops confirmation on account change, never retargeting the new account", async () => {
    const user = userEvent.setup();
    const sent = vi.fn();
    server.use(
      http.delete(`${base}/:id/transactions/:txn`, () => {
        sent();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { rerender } = render(<TransactionLedger portfolioId={1} />);
    await user.click(
      await screen.findByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
    );
    rerender(<TransactionLedger portfolioId={2} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(sent).not.toHaveBeenCalled();
  });
});

it("refreshes holding history and return after deleting its last event in filtered ledger", async () => {
  const user = userEvent.setup();
  render(<HoldingDetail portfolioId={1} ticker="MSFT" />);
  await user.click(
    await screen.findByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
  );
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Delete Transaction",
    }),
  );
  expect(await screen.findByText(/removed from the active ledger/)).toBeInTheDocument();
  expect(await screen.findByText(/No ledger position reported/)).toBeInTheDocument();
  expect(await screen.findByText("No transactions yet.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "MSFT" })).toBeInTheDocument();
});

function Selector() {
  const { select } = usePortfolioSelection();
  return <button onClick={() => select(2)}>Switch account</button>;
}
it("refreshes dashboard holdings and allocations after success", async () => {
  const user = userEvent.setup();
  window.localStorage.setItem("am.selected.portfolio", "1");
  render(
    <PortfolioSelectionProvider>
      <Selector />
      <Dashboard page="ledger" />
    </PortfolioSelectionProvider>,
  );
  await user.click(
    await screen.findByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
  );
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Delete Transaction",
    }),
  );
  await waitFor(() =>
    expect(
      screen.getByText(/A transaction was removed from the active ledger/),
    ).toBeInTheDocument(),
  );
  await user.click(screen.getByRole("button", { name: "Switch account" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  window.localStorage.clear();
});

it("distinguishes identical financial rows by stable IDs", async () => {
  const original = getTransactions(1)!.find((row) => row.id === 103)!;
  getTransactions(1)!.push({ ...original, id: 105 });
  const user = userEvent.setup();
  render(<TransactionLedger portfolioId={1} ticker="AAPL" />);
  await user.click(
    await screen.findByRole("button", { name: /Delete AAPL DIVIDEND Transaction 105/ }),
  );
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Delete Transaction",
    }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: /Transaction 105/ }),
    ).not.toBeInTheDocument(),
  );
  expect(
    screen.getByRole("button", { name: /Delete AAPL DIVIDEND Transaction 103/ }),
  ).toBeInTheDocument();
  expect(getTransactions(1)!.find((row) => row.id === 103)).toEqual(original);
});
it("leaves the row intact on server failure and on network failure", async () => {
  const user = userEvent.setup();
  server.use(
    http.delete(`${base}/1/transactions/102`, () =>
      HttpResponse.json({ detail: "Server unavailable" }, { status: 500 }),
    ),
  );
  render(<TransactionLedger portfolioId={1} />);
  await user.click(
    await screen.findByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
  );
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Delete Transaction",
    }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Server unavailable");
  expect(
    screen.getByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
  ).toBeInTheDocument();
  server.use(http.delete(`${base}/1/transactions/102`, () => HttpResponse.error()));
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Delete Transaction",
    }),
  );
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
  ).toBeInTheDocument();
});
it("does not set state or refresh a different account after an in-flight deletion unmounts", async () => {
  const user = userEvent.setup();
  let finish!: () => void;
  server.use(
    http.delete(`${base}/1/transactions/102`, async () => {
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const changed = vi.fn();
  const { rerender } = render(
    <TransactionLedger portfolioId={1} onDeleted={changed} />,
  );
  await user.click(
    await screen.findByRole("button", { name: /Delete MSFT BUY Transaction 102/ }),
  );
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Delete Transaction",
    }),
  );
  rerender(<TransactionLedger portfolioId={2} onDeleted={changed} />);
  expect(screen.queryByRole("dialog")).toBeNull();
  finish();
  await screen.findByText("No transactions yet.");
  expect(changed).not.toHaveBeenCalled();
});

it("does not infer incomplete history from missing prices or an undefined return", async () => {
  render(<HoldingsTable portfolioId={2} />);
  const aapl = (await screen.findByRole("link", { name: "AAPL" })).closest("tr")!;
  expect(within(aapl).queryByText("History not confirmed")).toBeNull();
  expect(within(aapl).getByText(/Price unavailable/)).toBeInTheDocument();
});
