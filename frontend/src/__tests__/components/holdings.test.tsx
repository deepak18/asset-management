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
    await user.click(screen.getByRole("button", { name: "Edit AAPL sector" }));
    await user.clear(screen.getByRole("textbox"));
    await user.type(screen.getByRole("textbox"), "Energy");
    server.use(
      http.patch(`${base}/1/holdings/AAPL`, () =>
        HttpResponse.json({ detail: "Save failed" }, { status: 500 }),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Save AAPL sector" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
    expect(screen.getByRole("textbox")).toHaveValue("Energy");
    expect(changed).not.toHaveBeenCalled();
    server.resetHandlers();
    await user.click(screen.getByRole("button", { name: "Save AAPL sector" }));
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
    await user.click(screen.getByRole("button", { name: "Edit AAPL sector" }));
    await user.clear(screen.getByRole("textbox"));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit AAPL sector" }));
    await user.clear(screen.getByRole("textbox"));
    await user.click(screen.getByRole("button", { name: "Save AAPL sector" }));
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
    await user.click(screen.getByRole("button", { name: "Edit SOFI industry" }));
    await user.type(
      screen.getByRole("textbox", { name: "SOFI industry" }),
      "Keep this draft",
    );
    await user.click(screen.getByRole("button", { name: "Edit PLTR sector" }));
    await user.type(screen.getByRole("textbox", { name: "PLTR sector" }), "Technology");
    await user.click(screen.getByRole("button", { name: "Save PLTR sector" }));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", { name: "PLTR sector" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("textbox", { name: "SOFI industry" })).toHaveValue(
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
      await screen.findByRole("button", { name: "Edit PLTR sector" }),
    ).toBeEnabled();
    expect(await screen.findByText(/Position values unavailable/)).toBeInTheDocument();
  });
});

describe("holding detail", () => {
  it("uses the URL portfolio, filters the ledger, and labels portfolio-only XIRR", async () => {
    render(<HoldingDetail portfolioId={1} ticker="AAPL" />);
    expect(await screen.findByRole("heading", { name: "AAPL" })).toBeInTheDocument();
    expect(await screen.findByText("USD 1,290.00")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to portfolio/ })).toHaveAttribute(
      "href",
      "/?portfolio=1",
    );
    expect(await screen.findByText(/whole portfolio, not this ticker/)).toBeInTheDocument();
    const ledger = await screen.findByRole("table");
    expect(within(ledger).queryByText("MSFT")).not.toBeInTheDocument();
    expect(within(ledger).getAllByRole("link", { name: "AAPL" })).toHaveLength(3);
  });

  it("saves classification, clears gaps, and preserves the other field's draft", async () => {
    const user = userEvent.setup();
    render(<HoldingDetail portfolioId={3} ticker="PLTR" />);
    await user.click(await screen.findByRole("button", { name: "Edit PLTR industry" }));
    await user.type(
      screen.getByRole("textbox", { name: "PLTR industry" }),
      "Draft industry",
    );
    await user.click(screen.getByRole("button", { name: "Edit PLTR sector" }));
    await user.type(screen.getByRole("textbox", { name: "PLTR sector" }), "Technology");
    await user.click(screen.getByRole("button", { name: "Save PLTR sector" }));
    await waitFor(() =>
      expect(screen.queryByText("Sector missing")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("textbox", { name: "PLTR industry" })).toHaveValue(
      "Draft industry",
    );
    expect(screen.getByText(/Source: MANUAL/)).toBeInTheDocument();
  });

  it("explains unpriced positions without a zero return", async () => {
    render(<HoldingDetail portfolioId={2} ticker="AAPL" />);
    expect(await screen.findByText(/Price unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Connect market data — XIRR/)).toBeInTheDocument();
    expect(screen.queryByText("0.00%")).not.toBeInTheDocument();
    const label = screen.getByText("Market value");
    expect(label.parentElement).toHaveTextContent("—");
  });
  it("shows 404 and analytics failure without inventing data", async () => {
    const { rerender } = render(<HoldingDetail portfolioId={1} ticker="MISSING" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Holding not found");
    server.use(
      http.get(`${base}/1/analytics`, () => HttpResponse.json({}, { status: 500 })),
    );
    rerender(<HoldingDetail portfolioId={1} ticker="AAPL" />);
    expect(
      await screen.findByRole("button", { name: "Edit AAPL sector" }),
    ).toBeEnabled();
    expect(
      await screen.findByText(/Could not load position values/),
    ).toBeInTheDocument();
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
