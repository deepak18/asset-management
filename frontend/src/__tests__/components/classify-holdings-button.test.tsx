import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ClassifyHoldingsButton } from "@/components/portfolio/classify-holdings-button";
import { env } from "@/lib/env";
import { apiClient } from "@/lib/api-client";
import { server } from "@/mocks/server";
import { classifyHoldings, setMarketDataConfigured } from "@/mocks/state";
import type { HoldingClassificationResult } from "@/types/domain";

const endpoint = `${env.apiBaseUrl}/api/v1/portfolios/3/holdings/classify`;
function result(
  patch: Partial<HoldingClassificationResult> = {},
): HoldingClassificationResult {
  return {
    portfolio_id: 3,
    classified: [],
    unresolved: [],
    skipped: [],
    failures: [],
    remaining: 0,
    next_cursor: null,
    ...patch,
  };
}

describe("ClassifyHoldingsButton", () => {
  it("follows next_cursor through one finite sweep and retries unresolved only on a fresh sweep", async () => {
    const user = userEvent.setup();
    const requests: (string | undefined)[] = [];
    const changed = vi.fn();
    server.use(
      http.post(endpoint, ({ request }) => {
        const cursor =
          new URL(request.url).searchParams.get("after_ticker") ?? undefined;
        requests.push(cursor);
        const attempt = classifyHoldings(3, false, 1, cursor);
        return attempt.ok
          ? HttpResponse.json(attempt.result)
          : HttpResponse.json({}, { status: 503 });
      }),
    );
    render(<ClassifyHoldingsButton portfolioId={3} onChanged={changed} />);
    await user.click(screen.getByRole("button", { name: "Classify holdings" }));
    expect(await screen.findByText(/Sweep complete/)).toBeInTheDocument();
    expect(requests).toEqual([undefined, "PLTR", "SOFI"]);
    expect(screen.getByText(/Classified 2 holdings/)).toBeInTheDocument();
    expect(screen.getByText(/Unresolved: ZZZZ/)).toBeInTheDocument();
    expect(changed).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Classify holdings" }));
    await waitFor(() => expect(requests).toHaveLength(4));
    expect(requests[3]).toBeUndefined();
    expect(await screen.findByText(/Classified 0 holdings/)).toBeInTheDocument();
  });

  it("advances past provider failures and distinguishes outages from missing configuration", async () => {
    const user = userEvent.setup();
    const cursors: (string | null)[] = [];
    server.use(
      http.post(endpoint, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("after_ticker");
        cursors.push(cursor);
        return HttpResponse.json(
          cursor
            ? result({
                unresolved: ["SOFI"],
                failures: [{ ticker: "SOFI", reason: "NO_PROFILE" }],
              })
            : result({
                unresolved: ["PLTR"],
                failures: [{ ticker: "PLTR", reason: "PROVIDER_UNAVAILABLE" }],
                remaining: 1,
                next_cursor: "PLTR",
              }),
        );
      }),
    );
    render(<ClassifyHoldingsButton portfolioId={3} />);
    await user.click(screen.getByRole("button", { name: "Classify holdings" }));
    expect(await screen.findByText(/Sweep complete/)).toBeInTheDocument();
    expect(cursors).toEqual([null, "PLTR"]);
    expect(
      screen.getByText(/Provider unavailable \(quota or outage\)/),
    ).toBeInTheDocument();
    expect(screen.getByText(/No usable profile returned/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Classify holdings" })).toBeEnabled();
  });

  it("points to the API key on 503 without offering retry", async () => {
    const user = userEvent.setup();
    setMarketDataConfigured(false);
    render(<ClassifyHoldingsButton portfolioId={3} />);
    await user.click(screen.getByRole("button", { name: "Classify holdings" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ALPHAVANTAGE_API_KEY");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("stops malformed cursor chains and refreshes partial successes", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    let calls = 0;
    server.use(
      http.post(endpoint, () => {
        calls++;
        return HttpResponse.json(
          result({
            classified:
              calls === 1
                ? [
                    {
                      ticker: "PLTR",
                      sector: "Technology",
                      classification_source: "PROVIDER",
                      data_gaps: [],
                    },
                  ]
                : [],
            remaining: 1,
            next_cursor: "PLTR",
          }),
        );
      }),
    );
    render(<ClassifyHoldingsButton portfolioId={3} onChanged={changed} />);
    await user.click(screen.getByRole("button", { name: "Classify holdings" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("advancing cursor");
    expect(calls).toBe(2);
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it("aborts in-flight work on unmount without starting the next request", async () => {
    const user = userEvent.setup();
    let signal: AbortSignal | undefined;
    let finish!: (value: HoldingClassificationResult) => void;
    const spy = vi
      .spyOn(apiClient, "classifyHoldings")
      .mockImplementation((_id, _options, requestSignal) => {
        signal = requestSignal;
        return new Promise((resolve) => {
          finish = resolve;
        });
      });
    try {
      const { unmount } = render(<ClassifyHoldingsButton portfolioId={3} />);
      await user.click(screen.getByRole("button", { name: "Classify holdings" }));
      unmount();
      expect(signal?.aborted).toBe(true);
      finish(result({ remaining: 1, next_cursor: "PLTR" }));
      await Promise.resolve();
      expect(spy).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });
});
