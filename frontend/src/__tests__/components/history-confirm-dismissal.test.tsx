import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, it, vi } from "vitest";
import { HoldingDetail } from "@/components/portfolio/holding-detail";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { HoldingHistoryReviewAction } from "@/components/portfolio/holding-history-review";
import { apiClient } from "@/lib/api-client";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { confirmHistoryReview, getHistoryReview } from "@/mocks/state";
import type { HoldingHistoryConfirmation } from "@/types/domain";

const base = `${env.apiBaseUrl}/api/v1/portfolios/1`;
const path = `${base}/holdings/AAPL/history`;

// AAPL exercises the same ticker-independent review flow as the reported AZO case.
it.each(["table", "detail"])(
  "%s keeps confirmation pending until 200, then dismisses, restores focus and reopens persisted history",
  async (surface) => {
    const user = userEvent.setup();
    const originalReturn = await apiClient.getHoldingAnalytics(1, "AAPL");
    let confirmed = false;
    let finish!: () => void;
    const posted = vi.fn();
    server.use(
      http.get(`${base}/holdings/AAPL/analytics`, () =>
        HttpResponse.json({
          ...originalReturn,
          money_weighted_return: confirmed ? "0.2715" : null,
          money_weighted_return_status: confirmed ? "OK" : "INCOMPLETE_HISTORY",
        }),
      ),
      http.post(path, async ({ request }) => {
        const body = (await request.json()) as HoldingHistoryConfirmation;
        posted(body);
        await new Promise<void>((resolve) => { finish = resolve; });
        const result = confirmHistoryReview(1, "AAPL", body.review_token)!;
        confirmed = true;
        return HttpResponse.json(result);
      }),
    );
    const historyReads = vi.spyOn(apiClient, "getHoldingHistory");
    const holdingsReads = vi.spyOn(apiClient, surface === "table" ? "listHoldings" : "getHolding");
    const changed = vi.fn();
    render(surface === "table"
      ? <HoldingsTable portfolioId={1} onChanged={changed} />
      : <HoldingDetail portfolioId={1} ticker="AAPL" />);
    const trigger = await screen.findByRole("button", { name: "Review History For AAPL" });
    if (surface === "detail") await screen.findByText(/Incomplete history/);
    await user.click(trigger);
    const dialog = screen.getByRole("dialog");
    const ui = within(dialog);
    await ui.findByRole("table");
    const token = getHistoryReview(1, "AAPL")!.review_token;
    const count = holdingsReads.mock.calls.length;
    await user.click(ui.getByRole("checkbox"));
    await user.dblClick(ui.getByRole("button", { name: "Confirm History" }));
    await waitFor(() => expect(finish).toBeTypeOf("function"));
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(ui.getByRole("button", { name: "Confirming…" })).toBeDisabled();
    expect(ui.getByRole("checkbox")).toBeDisabled();
    expect(confirmed).toBe(false);
    expect(posted).toHaveBeenCalledExactlyOnceWith({ review_token: token, confirmed: true });
    expect(historyReads).toHaveBeenCalledTimes(1);
    finish();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(trigger).toHaveFocus();
    await waitFor(() => expect(holdingsReads.mock.calls.length).toBeGreaterThan(count));
    // A closing review must not issue an immediately discarded refresh GET.
    expect(historyReads).toHaveBeenCalledTimes(1);
    if (surface === "table") expect(changed).toHaveBeenCalledTimes(1);
    else expect(await screen.findByText("+27.15%")).toBeInTheDocument();
    await user.click(trigger);
    const timestamp = getHistoryReview(1, "AAPL")!.confirmed_at!;
    expect(await within(screen.getByRole("dialog")).findByText(`History confirmed / complete — ${timestamp}`)).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(historyReads).toHaveBeenCalledTimes(2);
  },
);

it.each([404, 422, 500, "network"] as const)(
  "does not dismiss or refresh on confirmation failure %s",
  async (failure) => {
    const user = userEvent.setup();
    const changed = vi.fn();
    server.use(http.post(path, () => failure === "network"
      ? HttpResponse.error()
      : HttpResponse.json({ detail: "Confirmation rejected" }, { status: failure })));
    render(<HoldingHistoryReviewAction portfolioId={1} ticker="AAPL" onChanged={changed} />);
    await user.click(screen.getByRole("button", { name: "Review History For AAPL" }));
    const dialog = screen.getByRole("dialog");
    const ui = within(dialog);
    await ui.findByRole("table");
    await user.click(ui.getByRole("checkbox"));
    await user.click(ui.getByRole("button", { name: "Confirm History" }));
    expect(await ui.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(ui.getByRole("checkbox")).toBeChecked();
    expect(ui.getByRole("button", { name: "Confirm History" })).toBeEnabled();
    expect(changed).not.toHaveBeenCalled();
  },
);
