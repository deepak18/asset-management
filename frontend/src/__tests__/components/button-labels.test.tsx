import { RouteHarness } from "./route-harness";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it } from "vitest";
import { Dashboard } from "@/components/portfolio/dashboard";
import { Nav } from "@/components/app-shell/nav";
import { PortfolioSelectionProvider } from "@/hooks/use-portfolio-selection";
import { getAnalytics, getHoldings, getTransactions } from "@/mocks/state";
import { AllocationCharts } from "@/components/portfolio/allocation-chart";
import { formatMoney, formatPercent } from "@/lib/format";
import type { AllocationWeight } from "@/types/domain";

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  window.localStorage.clear();
  window.localStorage.setItem("am.selected.portfolio", "1");
});

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.classList.remove("dark");
});

async function renderDashboard() {
  const user = userEvent.setup();
  render(
    <PortfolioSelectionProvider>
      <Nav />
      <Dashboard />
    </PortfolioSelectionProvider>,
  );
  // Portfolio selection loads before panel reads; parallel jsdom/MSW workers
  // can exceed the default 1s wait even though no handler delays the response.
  await screen.findByRole(
    "button",
    { name: "Review History For AAPL" },
    { timeout: 3_000 },
  );
  return user;
}

it("uses explicit Title Case and accessible names for every fixed dashboard action without changing allocation data", async () => {
  await renderDashboard();
  await screen.findByRole("button", { name: "Delete AAPL BUY Transaction 101" });
  const categoryButtons = new Set<HTMLElement>();
  for (const [title, rows] of [
    ["Allocation by sector", getAnalytics(1)!.allocation_by_sector],
    ["Allocation by industry", getAnalytics(1)!.allocation_by_industry],
  ] as const) {
    const list = await screen.findByRole("list", { name: `${title} categories` });
    expect(within(list).getAllByRole("button")).toHaveLength(rows.length);
    for (const row of rows) {
      const name = `${row.key} ${formatMoney(row.market_value, "USD")} ${formatPercent(row.weight)}`;
      const button = within(list).getByRole("button", { name });
      expect(button).toHaveAccessibleName(name);
      expect(button).toHaveAttribute("aria-pressed", "false");
      categoryButtons.add(button);
    }
  }
  const visible = new Set([
    "Clear Selection",
    "New Portfolio",
    "Classify Holdings",
    "Review History",
    "Delete",
    "Add",
    "Add Position",
    "Add Transaction",
    "",
  ]);
  const names = new Set([
    "Clear Selection",
    "New Portfolio",
    "Classify Holdings",
    "Add",
    "Add Position",
    "Add Transaction",
    "Toggle Theme",
  ]);
  for (const holding of getHoldings(1)!) {
    names.add(`Review History For ${holding.ticker}`);
    names.add(`Edit ${holding.ticker} Sector`);
    names.add(`Edit ${holding.ticker} Industry`);
  }
  for (const row of getTransactions(1)!)
    names.add(`Delete ${row.ticker} ${row.type} Transaction ${row.id}`);
  for (const button of screen.getAllByRole("button")) {
    if (categoryButtons.has(button)) continue;
    expect(visible.has(button.textContent!.trim())).toBe(true);
    const name = button.getAttribute("aria-label") ?? button.textContent!.trim();
    expect(names.has(name)).toBe(true);
    expect(button).toHaveAccessibleName(name);
  }
  expect(screen.queryByLabelText("Upload Broker Statement")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Vanguard CSV")).not.toBeInTheDocument();
});

it("preserves ticker casing in the watchlist removal action", async () => {
  const user = await renderDashboard();
  await user.type(screen.getByRole("textbox", { name: "Add ticker" }), "NVDA");
  await user.click(screen.getByRole("button", { name: "Add" }));
  expect(screen.getByRole("button", { name: "Remove NVDA" })).toBeInTheDocument();
});

it("uses Title Case for portfolio creation dialog controls", async () => {
  const user = await renderDashboard();
  await user.click(screen.getByRole("button", { name: "New Portfolio" }));
  const ui = within(screen.getByRole("dialog"));
  expect(
    ui
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label") ?? button.textContent),
  ).toEqual(["Close Dialog", "Cancel", "Create"]);
  await user.click(ui.getByRole("button", { name: "Cancel" }));
});

it("uses Title Case for loaded holding-history dialog controls", async () => {
  const user = await renderDashboard();
  await user.click(screen.getByRole("button", { name: "Review History For AAPL" }));
  const ui = within(screen.getByRole("dialog"));
  await ui.findByRole("table");
  expect(
    ui
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label") ?? button.textContent),
  ).toEqual([
    "Close Dialog",
    "Reload History / Retry",
    "Add Transaction",
    "Confirm History",
    "Cancel",
  ]);
  await user.click(ui.getByRole("button", { name: "Cancel" }));
});

it("uses Title Case for the ticker-scoped classification save action", async () => {
  const user = await renderDashboard();
  await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
  expect(screen.getByRole("button", { name: "Save AAPL Sector" })).toHaveTextContent(
    "Save",
  );
  await user.click(screen.getByRole("button", { name: "Cancel" }));
});

it("uses Title Case for transaction deletion controls without changing classification data", async () => {
  const user = await renderDashboard();
  await user.click(
    await screen.findByRole("button", { name: "Delete AAPL BUY Transaction 101" }),
  );
  expect(
    within(screen.getByRole("dialog"))
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label") ?? button.textContent),
  ).toEqual(["Close Dialog", "Cancel", "Delete Transaction"]);
  expect(screen.getAllByText("Consumer Electronics").length).toBeGreaterThan(0);
});

it("preserves category data casing independently of fixed action Title Case", () => {
  const rows: AllocationWeight[] = [
    { key: "UNCLASSIFIED", market_value: "50", weight: "0.5" },
    { key: "software infrastructure", market_value: "30", weight: "0.3" },
    { key: "eCommerce / API", market_value: "20", weight: "0.2" },
  ];
  render(<AllocationCharts currency="USD" bySector={rows} byIndustry={rows} />);
  for (const title of ["Allocation by sector", "Allocation by industry"]) {
    const list = screen.getByRole("list", { name: `${title} categories` });
    expect(
      within(list)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual([
      "UNCLASSIFIEDUSD 50.0050.00%",
      "software infrastructureUSD 30.0030.00%",
      "eCommerce / APIUSD 20.0020.00%",
    ]);
    expect(
      within(list).getByRole("button", {
        name: "UNCLASSIFIED USD 50.00 50.00%",
      }),
    ).toBeInTheDocument();
    expect(
      within(list).getByRole("button", {
        name: "software infrastructure USD 30.00 30.00%",
      }),
    ).toBeInTheDocument();
    expect(
      within(list).getByRole("button", {
        name: "eCommerce / API USD 20.00 20.00%",
      }),
    ).toBeInTheDocument();
  }
  const clearButtons = screen.getAllByRole("button", {
    name: "Clear Selection",
  });
  expect(clearButtons).toHaveLength(2);
  for (const button of clearButtons) {
    expect(button.textContent).toBe("Clear Selection");
    expect(button).toBeDisabled();
  }
});

it("keeps import and settings action labels on their dedicated routes", async () => {
  const user = userEvent.setup();
  window.history.replaceState(null, "", "/imports");
  render(
    <PortfolioSelectionProvider>
      <RouteHarness />
    </PortfolioSelectionProvider>,
  );
  expect(await screen.findByRole("button", { name: "Choose File" })).toHaveTextContent(
    "Choose File",
  );
  expect(screen.getByLabelText("Upload Broker Statement")).toHaveAttribute(
    "type",
    "file",
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Brokerage" }),
    "vanguard",
  );
  expect(
    screen.getByRole("button", { name: "Preview Vanguard Import" }),
  ).toHaveTextContent("Preview Vanguard Import");
  expect(
    screen.getByRole("button", { name: "Reload Retirement History" }),
  ).toHaveTextContent("Reload Retirement History");
  const nav = within(screen.getByRole("navigation", { name: "Primary navigation" }));
  for (const name of [
    "Reported Holdings",
    "Ledger Analytics",
    "Imports",
    "Account Settings",
  ])
    expect(nav.getByRole("link", { name })).toHaveAccessibleName(name);
  await user.click(nav.getByRole("link", { name: "Account Settings" }));
  expect(
    await screen.findByRole("button", { name: "Edit Account Settings" }),
  ).toHaveTextContent("Edit Account Settings");
  window.history.replaceState(null, "", "/");
});
