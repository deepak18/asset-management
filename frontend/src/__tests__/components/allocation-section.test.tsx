import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";
import { AllocationSection } from "@/components/portfolio/allocation-section";
import { analyticsPriced } from "@/mocks/fixtures";
import { server } from "@/mocks/server";
import type { PortfolioAnalytics } from "@/types/domain";

const endpoint = "http://localhost:8000/api/v1/portfolios/:id/analytics";
function response(id: number, key = "Technology"): PortfolioAnalytics {
  return {
    ...analyticsPriced,
    portfolio: { ...analyticsPriced.portfolio, id },
    allocation_by_sector: [{ key, market_value: "42.125", weight: "1" }],
    allocation_by_industry: [],
  };
}

it("remounts selection and loading state across portfolios even with identical category keys", async () => {
  const user = userEvent.setup();
  server.use(
    http.get(endpoint, ({ params }) => HttpResponse.json(response(Number(params.id)))),
  );
  const { rerender } = render(<AllocationSection portfolioId={1} />);
  expect(screen.getAllByRole("status", { name: "Loading" })[0]).toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: /^Technology / }));
  expect(screen.getByRole("button", { name: /^Technology / })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  rerender(<AllocationSection portfolioId={2} />);
  expect(
    screen.queryByRole("button", { name: /^Technology / }),
  ).not.toBeInTheDocument();
  expect(await screen.findByRole("button", { name: /^Technology / })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
});

it("ignores late responses from an abandoned portfolio and refreshes allocation data by token", async () => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  let started!: () => void;
  const requested = new Promise<void>((resolve) => {
    started = resolve;
  });
  let currentKey = "Current";
  server.use(
    http.get(endpoint, async ({ params }) => {
      const id = Number(params.id);
      if (id === 1) {
        started();
        await pending;
        return HttpResponse.json(response(1, "Abandoned"));
      }
      return HttpResponse.json(response(id, currentKey));
    }),
  );
  const { rerender } = render(<AllocationSection portfolioId={1} />);
  await requested;
  rerender(<AllocationSection portfolioId={2} />);
  expect(await screen.findByRole("button", { name: /^Current / })).toBeInTheDocument();
  release();
  currentKey = "Refreshed";
  rerender(<AllocationSection portfolioId={2} refreshToken={1} />);
  const refreshed = await screen.findByRole("button", { name: /^Refreshed / });
  expect(within(refreshed).getByText("USD 42.13")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText("Abandoned")).not.toBeInTheDocument());
  expect(screen.queryByRole("button", { name: /^Current / })).not.toBeInTheDocument();
});

it("shows API failure honestly and recovers to unavailable allocations on refresh", async () => {
  server.use(
    http.get(endpoint, () =>
      HttpResponse.json({ detail: "Unavailable" }, { status: 503 }),
    ),
  );
  const { rerender } = render(<AllocationSection portfolioId={1} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not load allocation data.",
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  server.use(
    http.get(endpoint, () =>
      HttpResponse.json({ ...response(1), allocation_by_sector: [] }),
    ),
  );
  rerender(<AllocationSection portfolioId={1} refreshToken={1} />);
  expect(
    await screen.findAllByText("Not priced — allocation unavailable."),
  ).toHaveLength(2);
});
