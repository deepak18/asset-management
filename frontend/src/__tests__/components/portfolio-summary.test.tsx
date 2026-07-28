import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { PortfolioSummary } from "@/components/portfolio/portfolio-summary";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";

describe("PortfolioSummary", () => {
  it("shows a loading state before data arrives", () => {
    render(<PortfolioSummary portfolioId={1} />);
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
  });

  it("renders priced figures formatted from Decimal strings", async () => {
    render(<PortfolioSummary portfolioId={1} />);
    expect(await screen.findByText("Growth Portfolio")).toBeInTheDocument();
    // market_value_base "3415.00" → grouped, currency-prefixed
    expect(screen.getByText("USD 3,415.00")).toBeInTheDocument();
    // unrealized_pnl_base "251.40" is a gain → signed "+"
    expect(screen.getByText("+USD 251.40")).toBeInTheDocument();
    // money_weighted_return "0.1842" → percent
    expect(screen.getByText("+18.42%")).toBeInTheDocument();
    expect(screen.getByText(/Priced 2026-07-24/)).toBeInTheDocument();
  });

  it("degrades honestly when the book is unpriced (no fake zero)", async () => {
    render(<PortfolioSummary portfolioId={2} />);
    expect(await screen.findByText("Unpriced Portfolio")).toBeInTheDocument();
    expect(screen.getByText("Not priced")).toBeInTheDocument();
    // Market value and XIRR are unknown → em dash, never "0"
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("Not computable")).toBeInTheDocument();
    expect(screen.getByText(/Unpriced: AAPL, MSFT/)).toBeInTheDocument();
  });

  it("renders an error state when the request fails", async () => {
    server.use(
      http.get(`${env.apiBaseUrl}/api/v1/portfolios/:id/analytics`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    render(<PortfolioSummary portfolioId={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load portfolio analytics.",
    );
  });
});
