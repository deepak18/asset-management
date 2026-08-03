import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { ManualTransactionForm } from "@/components/portfolio/manual-transaction-form";
import type { TransactionInput } from "@/types/domain";

function captureTransactions(sink: (body: TransactionInput[]) => void) {
  server.use(
    http.post(`${env.apiBaseUrl}/api/v1/portfolios/1/transactions`, async ({ request }) => {
      const body = (await request.json()) as TransactionInput[];
      sink(body);
      return HttpResponse.json(
        { portfolio_id: 1, created_transactions: body.length, tickers: ["AAPL"], warnings: [] },
        { status: 201 },
      );
    }),
  );
}

describe("ManualTransactionForm", () => {
  it("shows trade fields for BUY and swaps to a single Amount field for DIVIDEND", async () => {
    const user = userEvent.setup();
    render(<ManualTransactionForm portfolioId={1} />);

    // BUY default → quantity + price + fees, no amount.
    expect(screen.getByLabelText("Quantity")).toBeInTheDocument();
    expect(screen.getByLabelText("Price / share")).toBeInTheDocument();
    expect(screen.queryByLabelText("Amount")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Type"), "DIVIDEND");
    expect(screen.getByLabelText("Amount")).toBeInTheDocument();
    expect(screen.queryByLabelText("Quantity")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Type"), "SPLIT");
    expect(screen.getByLabelText("Split ratio")).toBeInTheDocument();
    expect(screen.queryByLabelText("Amount")).not.toBeInTheDocument();
  });

  it("submits a DIVIDEND with only the relevant amount field, then refetches", async () => {
    const user = userEvent.setup();
    let captured: TransactionInput[] = [];
    captureTransactions((b) => (captured = b));
    const onSuccess = vi.fn();

    render(<ManualTransactionForm portfolioId={1} onSuccess={onSuccess} />);

    await user.type(screen.getByLabelText("Ticker"), "aapl");
    await user.selectOptions(screen.getByLabelText("Type"), "DIVIDEND");
    await user.type(screen.getByLabelText("Amount"), "2.40");
    await user.type(screen.getByLabelText("Trade date"), "2024-03-10");
    await user.click(screen.getByRole("button", { name: "Add transaction" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(captured[0]).toMatchObject({ ticker: "AAPL", type: "DIVIDEND", amount: "2.40" });
  });

  it("requires a trade date", async () => {
    const user = userEvent.setup();
    render(<ManualTransactionForm portfolioId={1} />);
    await user.type(screen.getByLabelText("Ticker"), "AAPL");
    await user.click(screen.getByRole("button", { name: "Add transaction" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Trade date is required.");
  });
});
