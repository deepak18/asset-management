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
    expect(await screen.findByRole("link", { name: "PLTR" })).toHaveAttribute(
      "href",
      "/portfolios/3/holdings/PLTR",
    );
    const sectorTitle = screen.getByText("Allocation by sector");
    const sectorCard = sectorTitle.closest("div.rounded-lg") as HTMLElement;
    await waitFor(() =>
      expect(within(sectorCard).getByText("60.00%")).toBeInTheDocument(),
    );
    expect(within(sectorCard).queryByRole("button")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit PLTR sector" }));
    await user.type(screen.getByRole("textbox", { name: "PLTR sector" }), "Energy");
    await user.click(screen.getByRole("button", { name: "Save PLTR sector" }));
    await waitFor(() => {
      const refreshed = screen
        .getByText("Allocation by sector")
        .closest("div.rounded-lg") as HTMLElement;
      expect(within(refreshed).getByText("Energy")).toBeInTheDocument();
      const unclassified = within(refreshed).getByText("UNCLASSIFIED").closest("li");
      expect(unclassified).toHaveTextContent("30.00%");
    });
    expect(window.localStorage.getItem("am.selected.portfolio")).toBe("3");
  } finally {
    window.history.replaceState(null, "", "/");
    window.localStorage.clear();
  }
});
