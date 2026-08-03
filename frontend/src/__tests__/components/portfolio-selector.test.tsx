import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { PortfolioSelectionProvider } from "@/hooks/use-portfolio-selection";
import { PortfolioSelector } from "@/components/portfolio/portfolio-selector";

function renderSelector() {
  return render(
    <PortfolioSelectionProvider>
      <PortfolioSelector />
    </PortfolioSelectionProvider>,
  );
}

describe("PortfolioSelector", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("lists portfolios and defaults the selection to the first, persisting it", async () => {
    renderSelector();

    const select = await screen.findByLabelText("Select portfolio");
    expect(select).toHaveValue("1");
    expect(screen.getByRole("option", { name: /Growth Portfolio · USD/ })).toBeInTheDocument();
    await waitFor(() =>
      expect(window.localStorage.getItem("am.selected.portfolio")).toBe("1"),
    );
  });

  it("persists a changed selection to localStorage", async () => {
    const user = userEvent.setup();
    renderSelector();

    const select = await screen.findByLabelText("Select portfolio");
    await user.selectOptions(select, "2");

    expect(select).toHaveValue("2");
    expect(window.localStorage.getItem("am.selected.portfolio")).toBe("2");
  });

  it("prompts to create a portfolio when there are none", async () => {
    server.use(
      http.get(`${env.apiBaseUrl}/api/v1/portfolios`, () => HttpResponse.json([])),
    );
    renderSelector();

    expect(
      await screen.findByRole("button", { name: /Create portfolio/ }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Select portfolio")).not.toBeInTheDocument();
  });
});
