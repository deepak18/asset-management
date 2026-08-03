import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { AddPositionForm } from "@/components/portfolio/add-position-form";
import type { PositionSnapshot } from "@/types/domain";

/** Capture the POST body so we can assert the "exactly one basis" contract. */
function capturePositions(sink: (body: PositionSnapshot[]) => void) {
  server.use(
    http.post(`${env.apiBaseUrl}/api/v1/portfolios/1/positions`, async ({ request }) => {
      const body = (await request.json()) as PositionSnapshot[];
      sink(body);
      return HttpResponse.json(
        { portfolio_id: 1, created_transactions: body.length, tickers: ["AAPL"], warnings: [] },
        { status: 201 },
      );
    }),
  );
}

describe("AddPositionForm", () => {
  it("submits a per-share snapshot with only cost_basis_per_share, then refetches", async () => {
    const user = userEvent.setup();
    let captured: PositionSnapshot[] = [];
    capturePositions((b) => (captured = b));
    const onSuccess = vi.fn();

    render(<AddPositionForm portfolioId={1} onSuccess={onSuccess} />);

    await user.type(screen.getByLabelText("Ticker"), "aapl");
    await user.type(screen.getByLabelText("Quantity"), "10");
    // Basis mode defaults to "per share".
    await user.type(screen.getByLabelText(/Cost per share/), "150");
    await user.click(screen.getByRole("button", { name: "Add position" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(captured[0]).toMatchObject({ ticker: "AAPL", cost_basis_per_share: "150" });
    expect(captured[0]).not.toHaveProperty("total_cost_basis", expect.anything());
    expect(captured[0]?.total_cost_basis).toBeUndefined();
    expect(screen.getByRole("status")).toHaveTextContent(/Recorded 1 lot/);
  });

  it("sends total_cost_basis (and never per-share) when the total mode is chosen", async () => {
    const user = userEvent.setup();
    let captured: PositionSnapshot[] = [];
    capturePositions((b) => (captured = b));

    render(<AddPositionForm portfolioId={1} />);

    await user.type(screen.getByLabelText("Ticker"), "msft");
    await user.type(screen.getByLabelText("Quantity"), "5");
    await user.selectOptions(screen.getByLabelText("Cost basis type"), "total");
    await user.type(screen.getByLabelText(/Total cost basis/), "2000");
    await user.click(screen.getByRole("button", { name: "Add position" }));

    await waitFor(() => expect(captured.length).toBe(1));
    expect(captured[0]?.total_cost_basis).toBe("2000");
    expect(captured[0]?.cost_basis_per_share).toBeUndefined();
  });

  it("requires a ticker", async () => {
    const user = userEvent.setup();
    render(<AddPositionForm portfolioId={1} />);
    await user.click(screen.getByRole("button", { name: "Add position" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ticker is required.");
  });
});
