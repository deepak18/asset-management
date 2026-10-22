import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";
import { AllocationSection } from "@/components/portfolio/allocation-section";
import { analyticsPriced, holdings as fixtureHoldings } from "@/mocks/fixtures";
import { server } from "@/mocks/server";
import type { HoldingInfo, PortfolioAnalytics } from "@/types/domain";

const endpoint = "http://localhost:8000/api/v1/portfolios/:id/analytics";
function response(id: number, key = "Technology"): PortfolioAnalytics {
  return {
    ...analyticsPriced,
    portfolio: { ...analyticsPriced.portfolio, id },
    allocation_by_sector: [{ key, market_value: "42.125", weight: "1" }],
    allocation_by_industry: [],
  };
}

const holdingsEndpoint = "http://localhost:8000/api/v1/portfolios/:id/holdings";
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
const technologyButton = () => screen.getByRole("button", { name: /^Technology / });

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

it("fetches holdings once for both charts, keeps charts available while loading and reveals the list without resetting a pin", async () => {
  const pending = deferred();
  let reads = 0;
  server.use(
    http.get(endpoint, () => HttpResponse.json(analyticsPriced)),
    http.get(holdingsEndpoint, async () => {
      reads += 1;
      await pending.promise;
      return HttpResponse.json(fixtureHoldings);
    }),
  );
  const user = userEvent.setup();
  const { container } = render(<AllocationSection portfolioId={1} />);
  await user.click(await screen.findByRole("button", { name: /^Technology / }));
  expect(screen.getByRole("status")).toHaveTextContent("Loading holdings breakdown");
  await user.hover(screen.getByRole("button", { name: /^Consumer Electronics / }));
  expect(screen.getAllByRole("status")).toHaveLength(2);
  await user.unhover(screen.getByRole("button", { name: /^Consumer Electronics / }));
  await act(async () => pending.resolve());
  const list = await screen.findByRole("list", { name: "Technology holdings" });
  expect(list).toHaveTextContent("AAPL37.78% of portfolio");
  expect(list).toHaveTextContent("MSFT62.22% of portfolio");
  expect(list).not.toHaveTextContent("XYZ");
  expect(technologyButton()).toHaveAttribute("aria-pressed", "true");
  fireEvent.mouseEnter(container.querySelectorAll(".recharts-pie-sector path")[1]!);
  fireEvent.mouseLeave(container.querySelectorAll(".recharts-pie-sector path")[1]!);
  expect(reads).toBe(1);
});

it("keeps allocation interactive on holdings failure and recovers both resources after refresh", async () => {
  const user = userEvent.setup();
  server.use(
    http.get(endpoint, () => HttpResponse.json(analyticsPriced)),
    http.get(holdingsEndpoint, () =>
      HttpResponse.json({ detail: "Unavailable" }, { status: 503 }),
    ),
  );
  const { rerender } = render(<AllocationSection portfolioId={1} />);
  await user.click(await screen.findByRole("button", { name: /^Technology / }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not load holdings breakdown",
  );
  expect(technologyButton()).toHaveAttribute("aria-pressed", "true");
  expect(
    screen.queryByRole("list", { name: "Technology holdings" }),
  ).not.toBeInTheDocument();
  server.use(http.get(holdingsEndpoint, () => HttpResponse.json(fixtureHoldings)));
  rerender(<AllocationSection portfolioId={1} refreshToken={1} />);
  expect(
    screen.queryByRole("button", { name: /^Technology / }),
  ).not.toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: /^Technology / }));
  expect(
    await screen.findByRole("list", { name: "Technology holdings" }),
  ).toHaveTextContent("AAPL");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("never pairs old classification membership with refreshed analytics and ignores an abandoned same-portfolio holdings read", async () => {
  const user = userEvent.setup();
  const pending = deferred();
  const started = deferred();
  const finished = deferred();
  let reads = 0;
  let version = 0;
  const reclassified: HoldingInfo[] = fixtureHoldings.map((h) => ({
    ...h,
    sector: h.ticker === "AAPL" ? "Energy" : h.sector,
  }));
  server.use(
    http.get(endpoint, () =>
      HttpResponse.json(
        version === 0
          ? analyticsPriced
          : ({
              ...analyticsPriced,
              allocation_by_sector: [
                { key: "Technology", market_value: "2125", weight: "0.6222" },
                { key: "Energy", market_value: "1290", weight: "0.3778" },
              ],
            } satisfies PortfolioAnalytics),
      ),
    ),
    http.get(holdingsEndpoint, async () => {
      reads += 1;
      if (reads === 2) {
        started.resolve();
        await pending.promise;
        finished.resolve();
        return HttpResponse.json(fixtureHoldings);
      }
      return HttpResponse.json(reads === 1 ? fixtureHoldings : reclassified);
    }),
  );
  const { rerender } = render(<AllocationSection portfolioId={1} />);
  await user.click(await screen.findByRole("button", { name: /^Technology / }));
  expect(
    await screen.findByRole("list", { name: "Technology holdings" }),
  ).toHaveTextContent("AAPL");
  version = 1;
  rerender(<AllocationSection portfolioId={1} refreshToken={1} />);
  expect(
    screen.queryByRole("list", { name: "Technology holdings" }),
  ).not.toBeInTheDocument();
  await started.promise;
  await user.click(await screen.findByRole("button", { name: /^Technology / }));
  expect(screen.getByRole("status")).toHaveTextContent("Loading holdings breakdown");
  expect(
    screen.queryByRole("list", { name: "Technology holdings" }),
  ).not.toBeInTheDocument();
  rerender(<AllocationSection portfolioId={1} refreshToken={2} />);
  await user.click(await screen.findByRole("button", { name: /^Technology / }));
  const list = await screen.findByRole("list", { name: "Technology holdings" });
  expect(list).toHaveTextContent("MSFT");
  expect(list).not.toHaveTextContent("AAPL");
  await act(async () => {
    pending.resolve();
    await finished.promise;
  });
  await user.click(screen.getByRole("button", { name: /^Energy / }));
  expect(screen.getByRole("list", { name: "Energy holdings" })).toHaveTextContent(
    "AAPL37.78% of portfolio",
  );
  await user.click(technologyButton());
  expect(
    screen.getByRole("list", { name: "Technology holdings" }),
  ).not.toHaveTextContent("AAPL");
  expect(reads).toBe(3);
});

it("isolates delayed holdings across portfolios with identical category keys and after unmount", async () => {
  const pending = deferred();
  const started = deferred();
  const finished = deferred();
  const user = userEvent.setup();
  server.use(
    http.get(endpoint, ({ params }) => HttpResponse.json(response(Number(params.id)))),
    http.get(holdingsEndpoint, async ({ params }) => {
      if (Number(params.id) === 1) {
        started.resolve();
        await pending.promise;
        finished.resolve();
        return HttpResponse.json([
          { ...fixtureHoldings[0]!, ticker: "AAPL", sector: "Technology" },
        ] satisfies HoldingInfo[]);
      }
      return HttpResponse.json([
        { ...fixtureHoldings[1]!, ticker: "MSFT", sector: "Technology" },
      ] satisfies HoldingInfo[]);
    }),
  );
  const { rerender, unmount } = render(<AllocationSection portfolioId={1} />);
  await started.promise;
  rerender(<AllocationSection portfolioId={2} />);
  await user.click(await screen.findByRole("button", { name: /^Technology / }));
  const list = await screen.findByRole("list", { name: "Technology holdings" });
  expect(list).toHaveTextContent("MSFT");
  expect(list).not.toHaveTextContent("AAPL");
  await act(async () => {
    pending.resolve();
    await finished.promise;
  });
  expect(
    screen.getByRole("list", { name: "Technology holdings" }),
  ).not.toHaveTextContent("AAPL");
  unmount();
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});

it("reports analytics 404 rather than inventing an empty portfolio", async () => {
  server.use(
    http.get(endpoint, () =>
      HttpResponse.json({ detail: "Portfolio not found" }, { status: 404 }),
    ),
  );
  render(<AllocationSection portfolioId={404} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not load allocation data.",
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
