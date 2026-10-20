import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import HoldingPage from "@/app/portfolios/[id]/holdings/[ticker]/page";

it("renders a deep-linked holding with normalized ticker and URL portfolio", async () => {
  render(await HoldingPage({ params: Promise.resolve({ id: "3", ticker: "pltr" }) }));
  expect(await screen.findByRole("heading", { name: "PLTR" })).toBeInTheDocument();
  expect(await screen.findByText(/Imported Portfolio/)).toBeInTheDocument();
});

it.each(["0", "-1", "abc", "1.5", "9007199254740992"])(
  "rejects invalid portfolio id %s",
  async (id) => {
    await expect(
      HoldingPage({ params: Promise.resolve({ id, ticker: "AAPL" }) }),
    ).rejects.toThrow();
  },
);
