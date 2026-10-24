import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { HoldingDetail } from "@/components/portfolio/holding-detail";
import { HoldingClassificationCell } from "@/components/portfolio/holding-classification-cell";
import { HoldingDataGaps } from "@/components/portfolio/holding-data-gaps";
import { env } from "@/lib/env";
import { apiClient } from "@/lib/api-client";
import { server } from "@/mocks/server";
import { holdings } from "@/mocks/fixtures";

const base = `${env.apiBaseUrl}/api/v1/portfolios`;

describe("holding classification cells", () => {
  it("preserves the draft on failure, then saves only the edited field", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(
      <HoldingClassificationCell
        portfolioId={1}
        holding={holdings[0]!}
        field="sector"
        onChanged={changed}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
    await user.clear(screen.getByRole("combobox"));
    await user.type(screen.getByRole("combobox"), "Energy");
    server.use(
      http.patch(`${base}/1/holdings/AAPL`, () =>
        HttpResponse.json({ detail: "Save failed" }, { status: 500 }),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Save AAPL Sector" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
    expect(screen.getByRole("combobox")).toHaveValue("Energy");
    expect(changed).not.toHaveBeenCalled();
    server.resetHandlers();
    await user.click(screen.getByRole("button", { name: "Save AAPL Sector" }));
    await waitFor(() =>
      expect(changed).toHaveBeenCalledWith(
        expect.objectContaining({
          sector: "Energy",
          industry: "Consumer Electronics",
          classification_source: "MANUAL",
        }),
      ),
    );
  });

  it("cancels without saving and explicitly clears a populated field", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(
      <HoldingClassificationCell
        portfolioId={1}
        holding={holdings[0]!}
        field="sector"
        onChanged={changed}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
    await user.clear(screen.getByRole("combobox"));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
    await user.clear(screen.getByRole("combobox"));
    await user.click(screen.getByRole("button", { name: "Save AAPL Sector" }));
    await waitFor(() =>
      expect(changed).toHaveBeenCalledWith(
        expect.objectContaining({ sector: null, data_gaps: ["SECTOR"] }),
      ),
    );
  });
});

describe("holdings table", () => {
  it("links tickers, explains gaps, and preserves another row's draft after saving", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(<HoldingsTable portfolioId={3} onChanged={changed} />);
    expect(await screen.findByRole("link", { name: "PLTR" })).toHaveAttribute(
      "href",
      "/portfolios/3/holdings/PLTR",
    );
    expect(screen.getAllByText("Sector missing").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Edit SOFI Industry" }));
    await user.type(
      screen.getByRole("combobox", { name: "SOFI industry" }),
      "Keep this draft",
    );
    await user.click(screen.getByRole("button", { name: "Edit PLTR Sector" }));
    await user.type(
      screen.getByRole("combobox", { name: "PLTR sector" }),
      "Technology",
    );
    await user.click(screen.getByRole("button", { name: "Save PLTR Sector" }));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        screen.queryByRole("combobox", { name: "PLTR sector" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("combobox", { name: "SOFI industry" })).toHaveValue(
      "Keep this draft",
    );
    expect(await apiClient.getHolding(3, "PLTR")).toMatchObject({
      sector: "Technology",
      industry: null,
    });
  });

  it("shows empty and failed holdings states", async () => {
    const { rerender } = render(<HoldingsTable portfolioId={99} />);
    expect(await screen.findByText(/No holdings yet/)).toBeInTheDocument();
    server.use(
      http.get(`${base}/404/holdings`, () => HttpResponse.json({}, { status: 500 })),
    );
    rerender(<HoldingsTable portfolioId={404} />);
    expect((await screen.findAllByRole("alert"))[0]).toBeInTheDocument();
  });

  it("keeps classification editable when analytics fails", async () => {
    server.use(
      http.get(`${base}/3/analytics`, () => HttpResponse.json({}, { status: 500 })),
    );
    render(<HoldingsTable portfolioId={3} />);
    expect(
      await screen.findByRole("button", { name: "Edit PLTR Sector" }),
    ).toBeEnabled();
    expect(await screen.findByText(/Position values unavailable/)).toBeInTheDocument();
  });
});

describe("holding detail", () => {
  it("uses the URL portfolio, filters the ledger, and reports this ticker's own XIRR", async () => {
    render(<HoldingDetail portfolioId={1} ticker="AAPL" />);
    expect(await screen.findByRole("heading", { name: "AAPL" })).toBeInTheDocument();
    expect(await screen.findByText("USD 1,290.00")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to portfolio/ })).toHaveAttribute(
      "href",
      "/ledger?portfolio=1",
    );
    // Holding-level XIRR: this ticker's own return, with its valuation provenance.
    expect(
      await screen.findByText(/This holding's money-weighted return/),
    ).toBeInTheDocument();
    expect(await screen.findByText("+18.42%")).toBeInTheDocument();
    expect(
      screen.getByText(/Annualized money-weighted return on your AAPL cash flows/),
    ).toBeInTheDocument();
    expect(screen.getByText(/from ALPHAVANTAGE GLOBAL_QUOTE/)).toBeInTheDocument();
    // The obsolete portfolio-wide fallback must be gone.
    expect(
      screen.queryByText(/whole portfolio, not this ticker/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/does not expose a per-holding XIRR/),
    ).not.toBeInTheDocument();
    const ledger = await screen.findByRole("table");
    expect(within(ledger).queryByText("MSFT")).not.toBeInTheDocument();
    expect(within(ledger).getAllByRole("link", { name: "AAPL" })).toHaveLength(3);
  });

  it("saves classification, clears gaps, and preserves the other field's draft", async () => {
    const user = userEvent.setup();
    render(<HoldingDetail portfolioId={3} ticker="PLTR" />);
    await user.click(await screen.findByRole("button", { name: "Edit PLTR Industry" }));
    await user.type(
      screen.getByRole("combobox", { name: "PLTR industry" }),
      "Draft industry",
    );
    await user.click(screen.getByRole("button", { name: "Edit PLTR Sector" }));
    await user.type(
      screen.getByRole("combobox", { name: "PLTR sector" }),
      "Technology",
    );
    await user.click(screen.getByRole("button", { name: "Save PLTR Sector" }));
    await waitFor(() =>
      expect(screen.queryByText("Sector missing")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("combobox", { name: "PLTR industry" })).toHaveValue(
      "Draft industry",
    );
    expect(screen.getByText(/Source: MANUAL/)).toBeInTheDocument();
  });

  it("explains unpriced positions without a zero return", async () => {
    render(<HoldingDetail portfolioId={2} ticker="AAPL" />);
    expect(await screen.findByText(/Price unavailable/)).toBeInTheDocument();
    expect(
      await screen.findByText(
        /Connect market data — this holding's return needs today's price/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("0.00%")).not.toBeInTheDocument();
    const label = screen.getByText("Market value");
    expect(label.parentElement).toHaveTextContent("—");
  });

  it("reports a closed holding's zero return independently of its unpriced portfolio", async () => {
    // Portfolio 2 is unpriced overall, yet MSFT is closed and valued from the
    // ledger — its own return is still available and renders a legitimate 0%.
    render(<HoldingDetail portfolioId={2} ticker="MSFT" />);
    expect(await screen.findByText("+0.00%")).toBeInTheDocument();
    expect(screen.getByText(/final ledger entry on 2026-04-01/)).toBeInTheDocument();
  });

  it("shows 404 and analytics failure without inventing data", async () => {
    const { rerender } = render(<HoldingDetail portfolioId={1} ticker="MISSING" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Holding not found");
    server.use(
      http.get(`${base}/1/analytics`, () => HttpResponse.json({}, { status: 500 })),
    );
    rerender(<HoldingDetail portfolioId={1} ticker="AAPL" />);
    expect(
      await screen.findByRole("button", { name: "Edit AAPL Sector" }),
    ).toBeEnabled();
    expect(
      await screen.findByText(/Could not load position values/),
    ).toBeInTheDocument();
  });
});

describe("holding-level XIRR statuses", () => {
  it("keeps the editor usable while the holding return is loading", async () => {
    server.use(
      http.get(`${base}/3/holdings/PLTR/analytics`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 300));
        return HttpResponse.json({}, { status: 500 });
      }),
    );
    render(<HoldingDetail portfolioId={3} ticker="PLTR" />);
    expect(
      await screen.findByRole("button", { name: "Edit PLTR Sector" }),
    ).toBeEnabled();
    expect(screen.queryByText(/Could not load this holding's return/)).toBeNull();
    expect(
      await screen.findByText(/Could not load this holding's return/),
    ).toBeInTheDocument();
  });

  it("treats a missing return as local to its card, not a missing holding", async () => {
    server.use(
      http.get(`${base}/3/holdings/PLTR/analytics`, () =>
        HttpResponse.json({ detail: "Holding not found" }, { status: 404 }),
      ),
    );
    render(<HoldingDetail portfolioId={3} ticker="PLTR" />);
    expect(
      await screen.findByText("No return reported for this holding."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit PLTR Sector" })).toBeEnabled();
  });

  it("renders a negative return with the existing percentage conventions", async () => {
    render(<HoldingDetail portfolioId={1} ticker="MSFT" />);
    expect(await screen.findByText("-5.30%")).toBeInTheDocument();
  });

  it.each([
    ["NVDA", "INCOMPLETE_HISTORY", /Incomplete history/],
    ["PLTR", "INSUFFICIENT_FLOWS", /Needs more history/],
    ["SOFI", "INVALID_HISTORY", /History needs review/],
  ] as const)(
    "renders %s (%s) as a dash with status-specific guidance, never 0%%",
    async (ticker, _status, guidance) => {
      render(<HoldingDetail portfolioId={3} ticker={ticker} />);
      expect(await screen.findByText(guidance)).toBeInTheDocument();
      expect(screen.queryByText("0.00%")).not.toBeInTheDocument();
      expect(screen.queryByText("+0.00%")).not.toBeInTheDocument();
    },
  );

  it("withholds a foreign-currency holding's return without suppressing a priced sibling", async () => {
    // Same portfolio (1): XYZ is MISSING_FX while AAPL is OK. One holding's gap
    // must not suppress the other's available return.
    render(<HoldingDetail portfolioId={1} ticker="XYZ" />);
    expect(await screen.findByText(/Missing FX rate/)).toBeInTheDocument();
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
    const sibling = await apiClient.getHoldingAnalytics(1, "AAPL");
    expect(sibling.money_weighted_return_status).toBe("OK");
    expect(sibling.money_weighted_return).toBe("0.1842");
  });

  it("keeps classification editable while the return is loading, then on failure", async () => {
    server.use(
      http.get(`${base}/3/holdings/PLTR/analytics`, () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );
    render(<HoldingDetail portfolioId={3} ticker="PLTR" />);
    expect(
      await screen.findByText(/Could not load this holding's return/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit PLTR Sector" })).toBeEnabled();
  });
});

it("describes non-classification gaps without offering a misleading input", () => {
  render(
    <HoldingDataGaps gaps={["SECTOR", "COST_BASIS", "SPLIT_RATIO", "TRANSACTION"]} />,
  );
  expect(screen.getByText("Cost basis needs attention")).toBeInTheDocument();
  expect(screen.getByText(/classification edits do not repair/)).toBeInTheDocument();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});
