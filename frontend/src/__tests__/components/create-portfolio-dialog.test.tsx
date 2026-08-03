import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { PortfolioSelectionProvider } from "@/hooks/use-portfolio-selection";
import { PortfolioSelector } from "@/components/portfolio/portfolio-selector";

/** The dialog is mounted inside the selector, so drive it end-to-end from there. */
function renderShell() {
  return render(
    <PortfolioSelectionProvider>
      <PortfolioSelector />
    </PortfolioSelectionProvider>,
  );
}

describe("CreatePortfolioDialog", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("creates a portfolio and auto-selects it", async () => {
    const user = userEvent.setup();
    renderShell();

    await screen.findByLabelText("Select portfolio");
    await user.click(screen.getByRole("button", { name: "New portfolio" }));

    const dialog = await screen.findByRole("dialog", { name: "Create portfolio" });
    await user.type(screen.getByLabelText("Name"), "My Fund");
    await user.click(screen.getByRole("button", { name: "Create" }));

    // The new portfolio appears and becomes the active selection.
    await waitFor(() =>
      expect(screen.getByLabelText("Select portfolio")).toHaveValue("100"),
    );
    expect(screen.getByRole("option", { name: /My Fund · USD/ })).toBeInTheDocument();
    expect(dialog).not.toBeInTheDocument();
  });

  it("requires a name", async () => {
    const user = userEvent.setup();
    renderShell();

    await screen.findByLabelText("Select portfolio");
    await user.click(screen.getByRole("button", { name: "New portfolio" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Name is required.");
  });
});
