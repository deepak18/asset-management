import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, expect, it, vi } from "vitest";
import { Dashboard } from "@/components/portfolio/dashboard";
import {
  PortfolioSelectionProvider,
  usePortfolioSelection,
} from "@/hooks/use-portfolio-selection";
import { apiClient } from "@/lib/api-client";
import { env } from "@/lib/env";
import { demoValuation } from "@/mocks/retirement-fixtures";
import { mockRetirement, updateMockAccount } from "@/mocks/state";
import { server } from "@/mocks/server";

const base = `${env.apiBaseUrl}/api/v1/portfolios`;

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

function Controls() {
  const { refreshData, select } = usePortfolioSelection();
  return (
    <>
      <button onClick={refreshData}>Refresh Test Account</button>
      <button onClick={() => select(1)}>Select Brokerage</button>
      <button onClick={() => select(99)}>Select Retirement</button>
    </>
  );
}

function mount(id = 1) {
  window.localStorage.setItem("am.selected.portfolio", String(id));
  render(
    <PortfolioSelectionProvider>
      <Controls />
      <Dashboard />
    </PortfolioSelectionProvider>,
  );
}

function gateValuation(id: number, fail = false, asOf = "2026-10-21") {
  let release!: () => void;
  let signal: AbortSignal | undefined;
  server.use(
    http.get(`${base}/${id}/valuations`, async ({ request }) => {
      signal = request.signal;
      await new Promise<void>((resolve) => { release = resolve; });
      return fail
        ? HttpResponse.json({ detail: "Valuation unavailable" }, { status: 500 })
        : HttpResponse.json(id === 99 ? demoValuation(id, asOf) : {
            portfolio_id: id,
            view: "REPORTED_SNAPSHOT",
            status: "EMPTY",
            snapshot: null,
          });
    }),
  );
  return {
    get signal() { return signal; },
    async started() { await waitFor(() => expect(signal).toBeDefined()); },
    async finish() { await act(async () => release()); },
  };
}

it("keeps the original dashboard history trigger mounted and restores focus through a same-account valuation refetch", async () => {
  const user = userEvent.setup();
  const holdings = vi.spyOn(apiClient, "listHoldings");
  const ledger = vi.spyOn(apiClient, "listTransactions");
  mount();
  const trigger = await screen.findByRole("button", { name: "Review History For AAPL" }, { timeout: 3000 });
  const pending = gateValuation(1);
  const holdingsCount = holdings.mock.calls.length;
  const ledgerCount = ledger.mock.calls.length;
  await user.click(trigger);
  const dialog = within(screen.getByRole("dialog"));
  await dialog.findByRole("table");
  await user.click(dialog.getByRole("checkbox"));
  await user.click(dialog.getByRole("button", { name: "Confirm History" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(trigger).toHaveFocus();
  expect(screen.getByRole("button", { name: "Review History For AAPL" })).toBe(trigger);
  await pending.started();
  expect(screen.getByText("Loading account valuation…")).toHaveAttribute("role", "status");
  expect(trigger).toBeInTheDocument();
  await waitFor(() => {
    expect(holdings.mock.calls.length).toBeGreaterThan(holdingsCount);
    expect(ledger.mock.calls.length).toBeGreaterThan(ledgerCount);
  });
  await pending.finish();
  await waitFor(() => expect(screen.queryByText("Loading account valuation…")).toBeNull());
  expect(trigger).toHaveFocus();
  await user.click(trigger);
  expect(await within(screen.getByRole("dialog")).findByText(/History confirmed \/ complete —/)).toBeInTheDocument();
});

it("keeps a legitimate ledger mounted on valuation refresh failure and recovery without losing form drafts", async () => {
  const user = userEvent.setup();
  mount();
  const trigger = await screen.findByRole("button", { name: "Review History For AAPL" }, { timeout: 3000 });
  // An open editor is local UI state, not a cached reported valuation.
  await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
  const draft = screen.getByRole("combobox", { name: "AAPL sector" });
  await user.clear(draft);
  await user.type(draft, "Unsaved Sector");
  const pending = gateValuation(1, true);
  await user.click(screen.getByRole("button", { name: "Refresh Test Account" }));
  await pending.started();
  expect(trigger).toBeInTheDocument();
  expect(draft).toHaveValue("Unsaved Sector");
  await pending.finish();
  await screen.findByRole("button", { name: "Reload Account View" });
  expect(trigger).toBeInTheDocument();
  expect(draft).toHaveValue("Unsaved Sector");
  const recovery = gateValuation(1);
  await user.click(screen.getByRole("button", { name: "Reload Account View" }));
  await recovery.started();
  await recovery.finish();
  await waitFor(() => expect(screen.queryByText("Loading account valuation…")).toBeNull());
  expect(screen.getByRole("button", { name: "Review History For AAPL" })).toBe(trigger);
  expect(draft).toHaveValue("Unsaved Sector");
});

it("never substitutes a ledger, stale total or empty prompt for a pending or failed reported refresh", async () => {
  const user = userEvent.setup();
  updateMockAccount(99, { account_type: "ROTH_401K" });
  mockRetirement(99).valuation = demoValuation(99, "2026-10-20");
  mount(99);
  await screen.findByRole("table", { name: "Reported holdings" });
  const pending = gateValuation(99, true);
  await user.click(screen.getByRole("button", { name: "Refresh Test Account" }));
  await pending.started();
  function expectNoBalance() {
    expect(screen.queryByRole("table", { name: "Reported holdings" })).toBeNull();
    expect(screen.queryByText(/USD 247.05/)).toBeNull();
    expect(screen.queryByText(/USD 0.00/)).toBeNull();
    expect(screen.queryByText(/No reported snapshot yet/)).toBeNull();
    expect(screen.queryByText("Allocation by sector")).toBeNull();
    expect(screen.getByRole("button", { name: "Reported Holdings" })).toHaveAttribute("aria-pressed", "true");
  }
  expectNoBalance();
  await pending.finish();
  await screen.findByRole("button", { name: "Reload Account View" });
  expectNoBalance();
  const recovery = gateValuation(99);
  await user.click(screen.getByRole("button", { name: "Reload Account View" }));
  await recovery.started();
  expectNoBalance();
  await recovery.finish();
  await screen.findByRole("table", { name: "Reported holdings" });
  expect(screen.getByText(/AVAILABLE · As of 2026-10-21 · VANGUARD/)).toBeInTheDocument();
});

it("resets the ledger boundary on account changes and ignores an abandoned reported refresh generation", async () => {
  const user = userEvent.setup();
  updateMockAccount(99, { account_type: "TRADITIONAL_IRA" });
  mockRetirement(99).valuation = demoValuation(99, "2026-10-20");
  mount(99);
  await screen.findByRole("table", { name: "Reported holdings" });
  await user.click(screen.getByRole("button", { name: "Ledger Analytics" }));
  await screen.findByText("Allocation by sector");
  const oldLedger = screen.getByRole("button", { name: "Add Position" });
  const abandoned = gateValuation(99, false, "2026-10-19");
  await user.click(screen.getByRole("button", { name: "Refresh Test Account" }));
  await abandoned.started();
  expect(oldLedger).toBeInTheDocument();
  // A newer generation must win even if an older request finishes last.
  const latest = gateValuation(99, false, "2026-10-22");
  await user.click(screen.getByRole("button", { name: "Refresh Test Account" }));
  await latest.started();
  expect(abandoned.signal?.aborted).toBe(true);
  await user.click(screen.getByRole("button", { name: "Reported Holdings" }));
  expect(screen.queryByRole("table", { name: "Reported holdings" })).toBeNull();
  await latest.finish();
  await screen.findByRole("table", { name: "Reported holdings" });
  await abandoned.finish();
  expect(screen.queryByText(/2026-10-19/)).toBeNull();
  expect(screen.getByText(/AVAILABLE · As of 2026-10-22 · VANGUARD/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Select Brokerage" }));
  await screen.findByRole("button", { name: "Review History For AAPL" });
  expect(oldLedger).not.toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Reported holdings" })).toBeNull();
  const initial = gateValuation(99);
  await user.click(screen.getByRole("button", { name: "Select Retirement" }));
  await initial.started();
  expect(screen.queryByRole("button", { name: "Review History For AAPL" })).toBeNull();
  expect(screen.queryByText("Allocation by sector")).toBeNull();
  expect(screen.queryByText(/No reported snapshot yet/)).toBeNull();
  await initial.finish();
  await screen.findByRole("table", { name: "Reported holdings" });
});
