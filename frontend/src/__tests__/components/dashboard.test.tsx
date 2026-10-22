import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { Dashboard } from "@/components/portfolio/dashboard";
import { PortfolioSelectionProvider } from "@/hooks/use-portfolio-selection";

it("returns to the requested portfolio and refreshes allocations after an inline edit", async () => {
  const user = userEvent.setup();
  window.localStorage.clear();
  window.localStorage.setItem("am.selected.portfolio", "1");
  window.history.replaceState(null, "", "/?portfolio=3");
  try {
    render(
      <PortfolioSelectionProvider>
        <Dashboard />
      </PortfolioSelectionProvider>,
    );
    // Portfolio selection (including the URL override) precedes panel reads;
    // allow parallel jsdom/MSW workers more than the default 1s startup wait.
    for (const link of await screen.findAllByRole(
      "link",
      { name: "PLTR" },
      { timeout: 3_000 },
    )) {
      expect(link).toHaveAttribute("href", "/portfolios/3/holdings/PLTR");
    }
    const sectorTitle = screen.getByText("Allocation by sector");
    const sectorCard = sectorTitle.closest("div.rounded-lg") as HTMLElement;
    await waitFor(() =>
      expect(within(sectorCard).getByText("60.00%")).toBeInTheDocument(),
    );
    const sector = within(sectorCard);
    const categories = sector.getByRole("list", {
      name: "Allocation by sector categories",
    });
    const unclassifiedButton = within(categories).getByRole("button", {
      name: "UNCLASSIFIED USD 6,000.00 60.00%",
    });
    const clear = sector.getByRole("button", { name: "Clear Selection" });
    expect(clear).toBeDisabled();
    await user.click(unclassifiedButton);
    expect(unclassifiedButton).toHaveAttribute("aria-pressed", "true");
    expect(sector.getByText("USD 6,000.00 · 60.00%")).toBeInTheDocument();
    const initialMembers = await sector.findByRole("list", {
      name: "UNCLASSIFIED holdings",
    });
    expect(initialMembers).toHaveTextContent("PLTR30.00% of portfolio");
    expect(initialMembers).toHaveTextContent("SOFI20.00% of portfolio");
    await user.click(clear);
    expect(unclassifiedButton).toHaveFocus();
    expect(unclassifiedButton).toHaveAttribute("aria-pressed", "false");
    await user.keyboard("{Enter}");
    expect(unclassifiedButton).toHaveAttribute("aria-pressed", "true");
    await user.keyboard(" ");
    expect(unclassifiedButton).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: "Edit PLTR Sector" }));
    await user.type(screen.getByRole("combobox", { name: "PLTR sector" }), "Energy");
    await user.click(screen.getByRole("button", { name: "Save PLTR Sector" }));
    await waitFor(() => {
      const refreshed = screen
        .getByText("Allocation by sector")
        .closest("div.rounded-lg") as HTMLElement;
      expect(within(refreshed).getByText("Energy")).toBeInTheDocument();
      const unclassified = within(refreshed).getByText("UNCLASSIFIED").closest("li");
      expect(unclassified).toHaveTextContent("30.00%");
      expect(
        within(refreshed).getByRole("button", { name: "Clear Selection" }),
      ).toBeDisabled();
      expect(
        within(refreshed).getByRole("button", {
          name: "UNCLASSIFIED USD 3,000.00 30.00%",
        }),
      ).toHaveAttribute("aria-pressed", "false");
    });
    expect(window.localStorage.getItem("am.selected.portfolio")).toBe("3");
    // Inspect the remounted chart, not the detached pre-refresh card.
    const refreshedSector = within(
      screen.getByText("Allocation by sector").closest("div.rounded-lg") as HTMLElement,
    );
    await user.click(refreshedSector.getByRole("button", { name: /^Energy / }));
    const energyMembers = await refreshedSector.findByRole("list", {
      name: "Energy holdings",
    });
    expect(energyMembers).toHaveTextContent("PLTR30.00% of portfolio");
    expect(energyMembers).not.toHaveTextContent("SOFI");
    await user.click(refreshedSector.getByRole("button", { name: /^UNCLASSIFIED / }));
    const remainingMembers = refreshedSector.getByRole("list", {
      name: "UNCLASSIFIED holdings",
    });
    expect(remainingMembers).toHaveTextContent("SOFI20.00% of portfolio");
    expect(remainingMembers).not.toHaveTextContent("PLTR");
  } finally {
    window.history.replaceState(null, "", "/");
    window.localStorage.clear();
  }
});
