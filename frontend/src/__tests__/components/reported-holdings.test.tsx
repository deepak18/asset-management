import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { ReportedHoldings } from "@/components/portfolio/reported-holdings";
import { Dashboard } from "@/components/portfolio/dashboard";
import {
  PortfolioSelectionProvider,
  usePortfolioSelection,
} from "@/hooks/use-portfolio-selection";
import { demoSecurity, demoValuation } from "@/mocks/retirement-fixtures";
import { mockRetirement, updateMockAccount } from "@/mocks/state";
import { server } from "@/mocks/server";
import { env } from "@/lib/env";
import { DASH } from "@/lib/format";

it("joins exact numeric security identities, formats decimals/nulls and reports partial provenance without ticker guesses", () => {
  const valuation = demoValuation(99, "2026-10-20");
  valuation.status = "PARTIAL";
  valuation.snapshot!.positions[0]!.reported_price = null;
  const view = render(
    <ReportedHoldings valuation={valuation} securities={[demoSecurity]} />,
  );
  const table = within(screen.getByRole("table", { name: "Reported holdings" }));
  expect(table.getByText("12.3456789012")).toBeInTheDocument();
  const row = table.getAllByRole("row")[1]!;
  expect(
    within(row)
      .getAllByRole("cell")
      .slice(2, 6)
      .map((cell) => cell.textContent),
  ).toEqual([DASH, "USD 247.05", DASH, DASH]);
  expect(row).toHaveTextContent("Example Balanced Trust");
  expect(row).toHaveTextContent("No confirmed ticker · UNKNOWN");
  expect(row).toHaveTextContent("2026-10-20 · VANGUARD · fictional-checksum");
  expect(screen.getByText(/Partial snapshot:/)).toBeInTheDocument();
  expect(screen.getByText(/returns unavailable/)).toBeInTheDocument();
  view.rerender(<ReportedHoldings valuation={valuation} securities={[]} />);
  expect(
    screen.getByRole("cell", { name: /Unknown security #701/ }),
  ).toBeInTheDocument();
  expect(screen.queryByText("ETF")).not.toBeInTheDocument();
});

it("shows an import prompt rather than zero for an empty snapshot", () => {
  render(
    <ReportedHoldings
      valuation={{
        portfolio_id: 99,
        view: "REPORTED_SNAPSHOT",
        status: "EMPTY",
        snapshot: null,
      }}
      securities={[]}
    />,
  );
  expect(screen.getByText(/No reported snapshot yet/)).toBeInTheDocument();
  expect(screen.queryByText(/USD 0/)).not.toBeInTheDocument();
});

it("automatically selects existing snapshots and retirement metadata, isolates stale reads on account switch and supports an explicit ledger toggle", async () => {
  const user = userEvent.setup();
  window.localStorage.setItem("am.selected.portfolio", "99");
  window.history.replaceState(null, "", "/");
  updateMockAccount(99, { account_type: "ROTH_401K" });
  mockRetirement(99).valuation = demoValuation(99, "2026-10-20");
  let release!: () => void;
  let signal: AbortSignal | undefined;
  server.use(
    http.get(
      `${env.apiBaseUrl}/api/v1/portfolios/99/valuations`,
      async ({ request }) => {
        signal = request.signal;
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        return HttpResponse.json(demoValuation(99, "2026-10-20"));
      },
    ),
  );
  function Switch() {
    const selection = usePortfolioSelection();
    return <button onClick={() => selection.select(1)}>Switch To Brokerage</button>;
  }
  render(
    <PortfolioSelectionProvider>
      <Switch />
      <Dashboard />
    </PortfolioSelectionProvider>,
  );
  await waitFor(() => expect(signal).toBeDefined());
  expect(screen.queryByText(/USD 0.00/)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Switch To Brokerage" }));
  await act(async () => release());
  expect(signal?.aborted).toBe(true);
  expect(
    await screen.findByText("Allocation by sector", {}, { timeout: 3000 }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("table", { name: "Reported holdings" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Reported Holdings" }));
  expect(screen.getByText(/No reported snapshot yet/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Ledger Analytics" }));
  expect(await screen.findByText("Allocation by sector")).toBeInTheDocument();
  window.localStorage.clear();
});

it("prefers a snapshot for an UNKNOWN account without combining ledger balances", async () => {
  const user = userEvent.setup();
  window.localStorage.setItem("am.selected.portfolio", "99");
  mockRetirement(99).valuation = demoValuation(99, "2026-10-20");
  render(
    <PortfolioSelectionProvider>
      <Dashboard />
    </PortfolioSelectionProvider>,
  );
  expect(
    await screen.findByRole("table", { name: "Reported holdings" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reported Holdings" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await user.click(screen.getByRole("button", { name: "Ledger Analytics" }));
  expect(await screen.findByText("Allocation by sector")).toBeInTheDocument();
  window.localStorage.clear();
});

it("opens a retirement account with no snapshot in the reported import-prompt view", async () => {
  window.localStorage.setItem("am.selected.portfolio", "99");
  updateMockAccount(99, { account_type: "TRADITIONAL_IRA" });
  render(
    <PortfolioSelectionProvider>
      <Dashboard />
    </PortfolioSelectionProvider>,
  );
  expect(await screen.findByText(/No reported snapshot yet/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reported Holdings" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.queryByText(/USD 0.00/)).not.toBeInTheDocument();
  expect(screen.queryByText("Allocation by sector")).not.toBeInTheDocument();
  window.localStorage.clear();
});
