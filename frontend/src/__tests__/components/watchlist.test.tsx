import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { Watchlist } from "@/components/portfolio/watchlist";

describe("Watchlist", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("starts empty and adds a normalized ticker", async () => {
    const user = userEvent.setup();
    render(<Watchlist />);
    expect(screen.getByText("Your watchlist is empty.")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Add ticker"), "nvda");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(screen.getByText("NVDA")).toBeInTheDocument();
    // Persisted upper-cased and de-duplicated
    expect(window.localStorage.getItem("am.watchlist.tickers")).toBe('["NVDA"]');
  });

  it("does not add duplicates (case-insensitive)", async () => {
    const user = userEvent.setup();
    render(<Watchlist />);
    const input = screen.getByLabelText("Add ticker");

    await user.type(input, "aapl");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await user.type(input, "AAPL");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(screen.getAllByText("AAPL")).toHaveLength(1);
  });

  it("removes a ticker", async () => {
    const user = userEvent.setup();
    render(<Watchlist />);

    await user.type(screen.getByLabelText("Add ticker"), "tsla");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove TSLA" }));
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
    expect(screen.getByText("Your watchlist is empty.")).toBeInTheDocument();
  });
});
