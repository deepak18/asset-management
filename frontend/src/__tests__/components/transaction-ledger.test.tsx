import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TransactionLedger } from "@/components/portfolio/transaction-ledger";

describe("TransactionLedger", () => {
  it("renders ledger rows from the typed client", async () => {
    render(<TransactionLedger portfolioId={1} />);
    expect(await screen.findByText("2024-01-15")).toBeInTheDocument();
    // BUY row: quantity + price present
    const buyRow = screen.getByText("2024-01-15").closest("tr");
    expect(buyRow).not.toBeNull();
    const buy = within(buyRow as HTMLElement);
    expect(buy.getByText("BUY")).toBeInTheDocument();
    expect(buy.getByText("USD 185.50")).toBeInTheDocument();
  });

  it("blanks irrelevant columns per event type (no fake zeros)", async () => {
    render(<TransactionLedger portfolioId={1} />);
    // DIVIDEND row shows amount but dashes quantity/price
    const divRow = (await screen.findByText("2024-03-10")).closest("tr");
    const div = within(divRow as HTMLElement);
    expect(div.getByText("DIVIDEND")).toBeInTheDocument();
    expect(div.getByText("USD 2.40")).toBeInTheDocument();
    expect(div.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("shows an empty state for a portfolio with no transactions", async () => {
    render(<TransactionLedger portfolioId={99} />);
    expect(await screen.findByText("No transactions yet.")).toBeInTheDocument();
  });
});
