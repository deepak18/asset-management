import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { Dashboard } from "@/components/portfolio/dashboard";
import { Nav } from "@/components/app-shell/nav";
import { PortfolioSelectionProvider } from "@/hooks/use-portfolio-selection";
import { getHoldings, getTransactions } from "@/mocks/state";

it("uses explicit Title Case for dashboard actions, icon actions and dialog controls without changing data", async () => {
  window.localStorage.clear();
  window.localStorage.setItem("am.selected.portfolio", "1");
  const user = userEvent.setup();
  try {
    render(
      <PortfolioSelectionProvider>
        <Nav />
        <Dashboard />
      </PortfolioSelectionProvider>,
    );
    await screen.findByRole("button", { name: "Review History For AAPL" });
    await screen.findByRole("button", { name: "Delete AAPL BUY Transaction 101" });
    const visible = new Set([
      "New Portfolio",
      "Classify Holdings",
      "Review History",
      "Delete",
      "Add",
      "Add Position",
      "Add Transaction",
      "Choose File",
      "",
    ]);
    const names = new Set([
      "New Portfolio",
      "Classify Holdings",
      "Add",
      "Add Position",
      "Add Transaction",
      "Choose File",
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
      expect(visible.has(button.textContent!.trim())).toBe(true);
      const name = button.getAttribute("aria-label") ?? button.textContent!.trim();
      expect(names.has(name)).toBe(true);
      expect(button).toHaveAccessibleName(name);
    }
    expect(screen.getByLabelText("Upload Broker Statement")).toHaveAttribute(
      "type",
      "file",
    );
    await user.type(screen.getByRole("textbox", { name: "Add ticker" }), "NVDA");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByRole("button", { name: "Remove NVDA" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New Portfolio" }));
    expect(
      within(screen.getByRole("dialog"))
        .getAllByRole("button")
        .map((button) => button.getAttribute("aria-label") ?? button.textContent),
    ).toEqual(["Close Dialog", "Cancel", "Create"]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
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
    await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
    expect(screen.getByRole("button", { name: "Save AAPL Sector" })).toHaveTextContent(
      "Save",
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(
      screen.getByRole("button", { name: "Delete AAPL BUY Transaction 101" }),
    );
    expect(
      within(screen.getByRole("dialog"))
        .getAllByRole("button")
        .map((button) => button.getAttribute("aria-label") ?? button.textContent),
    ).toEqual(["Close Dialog", "Cancel", "Delete Transaction"]);
    expect(screen.getAllByText("Consumer Electronics").length).toBeGreaterThan(0);
  } finally {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
  }
});
