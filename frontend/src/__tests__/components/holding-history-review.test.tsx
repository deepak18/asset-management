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
import { expect, it, vi } from "vitest";
import { HoldingHistoryReviewAction } from "@/components/portfolio/holding-history-review";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { HoldingDetail } from "@/components/portfolio/holding-detail";
import { ManualTransactionForm } from "@/components/portfolio/manual-transaction-form";
import { Dashboard } from "@/components/portfolio/dashboard";
import { PortfolioSelectionProvider } from "@/hooks/use-portfolio-selection";
import { apiClient } from "@/lib/api-client";
import { env } from "@/lib/env";
import {
  addMockTransactions,
  getHistoryReview,
  getHoldings,
  getTransactions,
} from "@/mocks/state";
import { server } from "@/mocks/server";
import type { HoldingHistoryReview } from "@/types/domain";

const base = `${env.apiBaseUrl}/api/v1/portfolios`;
const path = `${base}/1/holdings/AAPL/history`;
async function open(ticker = "AAPL") {
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", { name: `Review History For ${ticker}` }),
  );
  const dialog = screen.getByRole("dialog");
  await within(dialog).findByRole("table");
  return { user, dialog, ui: within(dialog) };
}

it.each(["table", "detail"])(
  "offers review from %s, displays scoped decimal ledger and complete without explicit confirmation",
  async (surface) => {
    render(
      surface === "table" ? (
        <HoldingsTable portfolioId={1} />
      ) : (
        <HoldingDetail portfolioId={1} ticker="AAPL" />
      ),
    );
    const { ui, dialog } = await open();
    expect(dialog).toHaveAccessibleName(/Review history: AAPL.*portfolio 1/i);
    expect(ui.getByText(/not explicitly confirmed/)).toBeInTheDocument();
    const rows = getTransactions(1)!.filter((row) => row.ticker === "AAPL");
    for (const row of rows)
      expect(ui.getByRole("cell", { name: String(row.id) })).toBeInTheDocument();
    expect(ui.queryByRole("cell", { name: "102" })).toBeNull();
    expect(ui.getAllByRole("cell", { name: "USD" })).toHaveLength(rows.length);
    expect(ui.getByRole("link", { name: /holding detail ledger/ })).toHaveAttribute(
      "href",
      "/portfolios/1/holdings/AAPL#holding-ledger",
    );
    expect(ui.getByRole("checkbox")).not.toBeChecked();
    expect(ui.getByRole("button", { name: "Confirm History" })).toBeDisabled();
  },
);

it("closes the detail review when opening its ledger without cancelling link navigation", async () => {
  const previousUrl = window.location.href;
  window.history.replaceState(null, "", "/portfolios/1/holdings/AAPL");
  try {
    render(<HoldingDetail portfolioId={1} ticker="AAPL" />);
    const { ui, user } = await open();
    const link = ui.getByRole("link", { name: /holding detail ledger/ });
    expect(link).toHaveAttribute("href", "/portfolios/1/holdings/AAPL#holding-ledger");
    const clicked = vi.fn<(event: MouseEvent) => void>();
    link.addEventListener("click", clicked, { once: true });
    await user.click(link);
    expect(clicked).toHaveBeenCalledTimes(1);
    expect(clicked.mock.calls[0]![0].defaultPrevented).toBe(false);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.getElementById("holding-ledger")).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/portfolios/1/holdings/AAPL#holding-ledger");
  } finally {
    window.history.replaceState(null, "", previousUrl);
  }
});

it("loads on open, retries GET errors, and cancellation and Escape never confirm", async () => {
  let finish!: () => void;
  let fail = true;
  const posted = vi.fn();
  server.use(
    http.get(path, async () => {
      if (fail) {
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        return HttpResponse.json({ detail: "History offline" }, { status: 500 });
      }
      return HttpResponse.json(getHistoryReview(1, "AAPL"));
    }),
    http.post(path, () => {
      posted();
      return HttpResponse.json({});
    }),
  );
  render(<HoldingHistoryReviewAction portfolioId={1} ticker="AAPL" />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /Review History/ }));
  expect(screen.getByText("Loading history…")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Confirm History" })).toBeDisabled();
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  finish();
  expect(await screen.findByRole("alert")).toHaveTextContent("History offline");
  fail = false;
  await user.click(screen.getByRole("button", { name: "Reload History / Retry" }));
  await screen.findByRole("table");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  await user.click(screen.getByRole("button", { name: /Review History/ }));
  await screen.findByRole("table");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  await user.keyboard("{Escape}");
  expect(posted).not.toHaveBeenCalled();
});

it("uses backend blocking_gaps, explains repairs, and cannot acknowledge blockers", async () => {
  const snapshot: HoldingHistoryReview = {
    ...getHistoryReview(1, "AAPL")!,
    history_complete: false,
    history_gaps: [
      "SNAPSHOT",
      "IMPORT_NOT_SUCCEEDED",
      "UNRESOLVED_EVENTS",
      "INVALID_LEDGER",
      "HISTORY_CHANGED",
    ],
    blocking_gaps: [
      "SNAPSHOT",
      "IMPORT_NOT_SUCCEEDED",
      "UNRESOLVED_EVENTS",
      "INVALID_LEDGER",
    ],
  };
  server.use(http.get(path, () => HttpResponse.json(snapshot)));
  render(<HoldingHistoryReviewAction portfolioId={1} ticker="AAPL" />);
  const { ui } = await open();
  expect(ui.getByRole("region", { name: "Confirmation blockers" })).toHaveTextContent(
    /inconsistent quantities/,
  );
  expect(
    ui.getByText(/A position snapshot is not an actual purchase/),
  ).toBeInTheDocument();
  expect(ui.getByText(/A checkbox cannot repair/)).toBeInTheDocument();
  expect(ui.getByRole("checkbox")).toBeDisabled();
  expect(ui.getByRole("button", { name: "Confirm History" })).toBeDisabled();
});

it("confirms current token once, dismisses dialog, refreshes detail diagnostics, XIRR, analytics and ledger", async () => {
  const holding = getHoldings(1)!.find((row) => row.ticker === "AAPL")!;
  holding.history_complete = false;
  holding.history_gaps = ["UNKNOWN_ORIGIN"];
  const reads = {
    holding: vi.spyOn(apiClient, "getHolding"),
    xirr: vi.spyOn(apiClient, "getHoldingAnalytics"),
    analytics: vi.spyOn(apiClient, "getAnalytics"),
    ledger: vi.spyOn(apiClient, "listTransactions"),
  };
  const post = vi.spyOn(apiClient, "confirmHoldingHistory");
  render(<HoldingDetail portfolioId={1} ticker="AAPL" />);
  const { ui, user } = await open();
  const counts = Object.values(reads).map((spy) => spy.mock.calls.length);
  await user.click(ui.getByRole("checkbox"));
  await user.dblClick(ui.getByRole("button", { name: "Confirm History" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(post).toHaveBeenCalledTimes(1);
  expect(post.mock.calls[0]![2]).toEqual({
    review_token: getHistoryReview(1, "AAPL")!.review_token,
    confirmed: true,
  });
  await waitFor(() =>
    Object.values(reads).forEach((spy, index) =>
      expect(spy.mock.calls.length).toBeGreaterThan(counts[index]!),
    ),
  );
  expect(screen.queryByText("Legacy transaction origin is unverified.")).toBeNull();
  await user.click(screen.getByRole("button", { name: /Review History For AAPL/ }));
  expect(await screen.findByText(/History confirmed \/ complete/)).toBeInTheDocument();
});

it("refreshes dashboard sibling summary, allocation and ledger reads after confirmation", async () => {
  window.localStorage.setItem("am.selected.portfolio", "1");
  const analytics = vi.spyOn(apiClient, "getAnalytics");
  const ledger = vi.spyOn(apiClient, "listTransactions");
  // Summary and allocation both consume getAnalytics; getPortfolio was only the now-dismissed review.
  const holdings = vi.spyOn(apiClient, "listHoldings");
  render(
    <PortfolioSelectionProvider>
      <Dashboard />
    </PortfolioSelectionProvider>,
  );
  const { user, ui } = await open();
  const counts = [
    analytics.mock.calls.length,
    ledger.mock.calls.length,
    holdings.mock.calls.length,
  ];
  await user.click(ui.getByRole("checkbox"));
  await user.click(ui.getByRole("button", { name: "Confirm History" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() =>
    [analytics, ledger, holdings].forEach((spy, index) =>
      expect(spy.mock.calls.length).toBeGreaterThan(counts[index]!),
    ),
  );
  window.localStorage.clear();
});

it.each(["BUY", "SELL", "DIVIDEND", "FEE", "SPLIT"])(
  "adds missing %s with a locked ticker, relevant fields and base currency; resets ack and reloads before confirmation",
  async (type) => {
    const changed = vi.fn();
    render(
      <>
        <ManualTransactionForm portfolioId={1} />
        <HoldingHistoryReviewAction portfolioId={1} ticker="AAPL" onChanged={changed} />
      </>,
    );
    const { ui, user } = await open();
    const ticker = ui.getByRole("textbox", { name: "Ticker" });
    expect(ticker).toHaveValue("AAPL");
    expect(ticker).toHaveAttribute("readonly");
    expect(ui.getByRole("combobox", { name: "Currency" })).toHaveValue("USD");
    expect(
      new Set(
        [...document.querySelectorAll("input, select")].map((element) => element.id),
      ).size,
    ).toBe(document.querySelectorAll("input, select").length);
    await user.click(ui.getByRole("checkbox"));
    await user.selectOptions(ui.getByRole("combobox", { name: "Type" }), type);
    fireEvent.change(ui.getByLabelText("Trade date"), {
      target: { value: "2024-06-15" },
    });
    if (type === "BUY" || type === "SELL") {
      await user.type(ui.getByLabelText("Quantity"), "1.25");
      await user.type(ui.getByLabelText("Price / share"), "123.123456789");
      await user.type(ui.getByLabelText("Fees (optional)"), "0.12");
    } else if (type === "SPLIT") {
      await user.type(ui.getByLabelText("Split ratio"), "2");
    } else await user.type(ui.getByLabelText("Amount"), "3.45");
    await user.click(ui.getByRole("button", { name: "Add Transaction" }));
    await ui.findByText(/Transaction added/);
    await ui.findByRole("table");
    expect(changed).toHaveBeenCalledTimes(1);
    expect(ui.getByRole("checkbox")).not.toBeChecked();
    expect(ui.getByRole("button", { name: "Confirm History" })).toBeDisabled();
    expect(ticker).toHaveValue("AAPL");
    const event = getTransactions(1)!.at(-1)!;
    expect(event).toMatchObject({
      portfolio_id: 1,
      ticker: "AAPL",
      type,
      currency: "USD",
      trade_date: "2024-06-15",
    });
    expect(new Set(getTransactions(1)!.map((row) => row.id)).size).toBe(
      getTransactions(1)!.length,
    );
    if (type === "BUY" || type === "SELL") expect(event.price).toBe("123.123456789");
    await user.click(ui.getByRole("checkbox"));
    await user.click(ui.getByRole("button", { name: "Confirm History" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  },
);

it("409 loads a fresh snapshot, shows change message, requires new acknowledgement and never retries POST automatically", async () => {
  const posted = vi.fn();
  const get = vi.spyOn(apiClient, "getHoldingHistory");
  server.use(
    http.post(path, () => {
      posted();
      return HttpResponse.json({ detail: "stale" }, { status: 409 });
    }),
  );
  render(<HoldingHistoryReviewAction portfolioId={1} ticker="AAPL" />);
  const { ui, user } = await open();
  await user.click(ui.getByRole("checkbox"));
  await user.click(ui.getByRole("button", { name: "Confirm History" }));
  await ui.findByText(/History changed or has blockers/);
  await ui.findByRole("table");
  expect(get).toHaveBeenCalledTimes(2);
  expect(posted).toHaveBeenCalledTimes(1);
  expect(ui.getByRole("checkbox")).not.toBeChecked();
  expect(ui.getByRole("button", { name: "Confirm History" })).toBeDisabled();
});

it("generic confirmation error retains acknowledgement and allows deliberate retry", async () => {
  let fail = true;
  server.use(
    http.post(path, () =>
      fail
        ? HttpResponse.json({ detail: "Try later" }, { status: 500 })
        : HttpResponse.json({
            ...getHistoryReview(1, "AAPL"),
            confirmed_at: "2026-01-01T00:00:00Z",
          }),
    ),
  );
  render(<HoldingHistoryReviewAction portfolioId={1} ticker="AAPL" />);
  const { ui, user } = await open();
  await user.click(ui.getByRole("checkbox"));
  await user.click(ui.getByRole("button", { name: "Confirm History" }));
  expect(await ui.findByRole("alert")).toHaveTextContent("Try later");
  expect(ui.getByRole("checkbox")).toBeChecked();
  fail = false;
  await user.click(ui.getByRole("button", { name: "Confirm History" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("preserves missing-record drafts on API failure and clears old acknowledgement", async () => {
  server.use(
    http.post(`${base}/1/transactions`, () =>
      HttpResponse.json({ detail: "Record rejected" }, { status: 422 }),
    ),
  );
  render(<HoldingHistoryReviewAction portfolioId={1} ticker="AAPL" />);
  const { ui, user } = await open();
  await user.click(ui.getByRole("checkbox"));
  fireEvent.change(ui.getByLabelText("Trade date"), {
    target: { value: "2024-06-15" },
  });
  await user.type(ui.getByLabelText("Quantity"), "2");
  await user.type(ui.getByLabelText("Price / share"), "20");
  await user.click(ui.getByRole("button", { name: "Add Transaction" }));
  expect(await ui.findByRole("alert")).toHaveTextContent("Record rejected");
  expect(ui.getByLabelText("Quantity")).toHaveValue("2");
  expect(ui.getByLabelText("Price / share")).toHaveValue("20");
  expect(ui.getByRole("checkbox")).not.toBeChecked();
  await user.click(ui.getByRole("button", { name: "Reload History / Retry" }));
  await ui.findByRole("table");
  expect(ui.getByLabelText("Quantity")).toHaveValue("2");
});

it.each(["close", "switch"])(
  "guards in-flight confirmation after %s without refreshing another scope",
  async (action) => {
    let finish!: () => void;
    server.use(
      http.post(path, async () => {
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        return HttpResponse.json({
          ...getHistoryReview(1, "AAPL"),
          confirmed_at: "2026-01-01T00:00:00Z",
        });
      }),
    );
    const changed = vi.fn();
    const { rerender } = render(
      <HoldingHistoryReviewAction portfolioId={1} ticker="AAPL" onChanged={changed} />,
    );
    const { ui, user } = await open();
    await user.click(ui.getByRole("checkbox"));
    await user.click(ui.getByRole("button", { name: "Confirm History" }));
    expect(ui.getByRole("button", { name: "Confirming…" })).toBeDisabled();
    await waitFor(() => expect(finish).toBeTypeOf("function"));
    if (action === "close")
      await user.click(ui.getByRole("button", { name: "Cancel" }));
    else
      rerender(
        <HoldingHistoryReviewAction
          portfolioId={2}
          ticker="AAPL"
          onChanged={changed}
        />,
      );
    finish();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(changed).not.toHaveBeenCalled();
  },
);

it("keeps keyboard focus within all review controls, including the repair form", async () => {
  render(<HoldingHistoryReviewAction portfolioId={1} ticker="AAPL" />);
  const { ui, user } = await open();
  ui.getByRole("button", { name: "Cancel" }).focus();
  await user.tab();
  expect(ui.getByRole("button", { name: "Close Dialog" })).toHaveFocus();
  await user.tab({ shift: true });
  expect(ui.getByRole("button", { name: "Cancel" })).toHaveFocus();
  ui.getByRole("textbox", { name: "Ticker" }).focus();
  await user.tab();
  expect(ui.getByRole("combobox", { name: "Type" })).toHaveFocus();
});

it("confirmed history does not fabricate an XIRR for an unpriced holding", async () => {
  server.use(
    http.get(`${base}/2/holdings/AAPL/history`, () =>
      HttpResponse.json({
        ...getHistoryReview(1, "AAPL"),
        confirmed_at: null,
        blocking_gaps: [],
      }),
    ),
    http.post(`${base}/2/holdings/AAPL/history`, () =>
      HttpResponse.json({
        ...getHistoryReview(1, "AAPL"),
        confirmed_at: "2026-01-01T00:00:00Z",
      }),
    ),
  );
  render(<HoldingDetail portfolioId={2} ticker="AAPL" />);
  const { ui, user } = await open();
  await user.click(ui.getByRole("checkbox"));
  await user.click(ui.getByRole("button", { name: "Confirm History" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  const card =
    screen
      .getByRole("heading", { name: "This holding's money-weighted return (XIRR)" })
      .closest("section") ??
    screen.getByRole("heading", { name: "This holding's money-weighted return (XIRR)" })
      .parentElement!.parentElement!;
  await waitFor(() =>
    expect(
      within(card as HTMLElement).getByText(/Connect market data/),
    ).toBeInTheDocument(),
  );
  expect(within(card as HTMLElement).getByText("—")).toBeInTheDocument();
  expect(within(card as HTMLElement).queryByText(/0\.00%/)).toBeNull();
});

it.each(["close", "switch"])(
  "discards a delayed review GET after %s, preserving the new scope snapshot",
  async (action) => {
    const late = getHistoryReview(1, "AAPL")!;
    addMockTransactions(
      2,
      [
        {
          ticker: "AAPL",
          type: "BUY",
          trade_date: "2025-01-01",
          currency: "USD",
          quantity: "2",
          price: "100",
          fees: "0",
          amount: "0",
          split_ratio: "1",
        },
      ],
      "SNAPSHOT",
    );
    let finish!: (review: HoldingHistoryReview) => void;
    const read = vi.spyOn(apiClient, "getHoldingHistory").mockImplementationOnce(
      () =>
        new Promise<HoldingHistoryReview>((resolve) => {
          finish = resolve;
        }),
    );
    const changed = vi.fn();
    const { rerender } = render(
      <HoldingHistoryReviewAction portfolioId={1} ticker="AAPL" onChanged={changed} />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Review History/ }));
    await waitFor(() => expect(finish).toBeTypeOf("function"));
    const signal = read.mock.calls[0]![2]!;
    if (action === "close") {
      await user.click(screen.getByRole("button", { name: "Cancel" }));
    } else {
      rerender(
        <HoldingHistoryReviewAction
          portfolioId={2}
          ticker="AAPL"
          onChanged={changed}
        />,
      );
      await user.click(screen.getByRole("button", { name: /Review History/ }));
      await within(screen.getByRole("dialog")).findByText("Synthetic snapshot");
    }
    expect(signal.aborted).toBe(true);
    // Deliberately resolve even after abort: the component must guard stale data.
    await act(async () => {
      finish(late);
    });
    if (action === "close") expect(screen.queryByRole("dialog")).toBeNull();
    else {
      const dialog = screen.getByRole("dialog");
      expect(dialog).toHaveAccessibleName(/portfolio 2/);
      expect(within(dialog).getByText("Synthetic snapshot")).toBeInTheDocument();
      expect(within(dialog).queryByRole("cell", { name: "101" })).toBeNull();
      expect(within(dialog).getByRole("checkbox")).not.toBeChecked();
    }
    expect(changed).not.toHaveBeenCalled();
  },
);
it("repairing a DIVIDEND in HoldingDetail refetches ledger and holding analytics while review remains open", async () => {
  const ledger = vi.spyOn(apiClient, "listTransactions");
  const xirr = vi.spyOn(apiClient, "getHoldingAnalytics");
  const write = vi.spyOn(apiClient, "addTransactions");
  render(<HoldingDetail portfolioId={1} ticker="AAPL" />);
  const { ui, user, dialog } = await open();
  await waitFor(() =>
    expect(
      document.querySelector('#holding-ledger [data-transaction-id="103"]'),
    ).not.toBeNull(),
  );
  const counts = [ledger.mock.calls.length, xirr.mock.calls.length];
  await user.click(ui.getByRole("checkbox"));
  await user.selectOptions(ui.getByRole("combobox", { name: "Type" }), "DIVIDEND");
  fireEvent.change(ui.getByLabelText("Trade date"), {
    target: { value: "2024-06-15" },
  });
  await user.type(ui.getByLabelText("Amount"), "3.45");
  await user.click(ui.getByRole("button", { name: "Add Transaction" }));
  await ui.findByText(/Transaction added/);
  await ui.findByRole("table");
  expect(screen.getByRole("dialog")).toBe(dialog);
  expect(write.mock.calls[0]![0]).toBe(1);
  expect(write.mock.calls[0]![1]).toEqual([
    {
      ticker: "AAPL",
      type: "DIVIDEND",
      trade_date: "2024-06-15",
      currency: "USD",
      amount: "3.45",
      quantity: "0",
      price: "0",
      fees: "0",
      split_ratio: "1",
    },
  ]);
  const added = getTransactions(1)!.at(-1)!;
  expect(added.history_origin).toBe("OBSERVED");
  expect(ui.getByRole("cell", { name: String(added.id) })).toBeInTheDocument();
  await waitFor(() => {
    expect(ledger.mock.calls.length).toBeGreaterThan(counts[0]!);
    expect(xirr.mock.calls.length).toBeGreaterThan(counts[1]!);
    expect(
      document.querySelector(`#holding-ledger [data-transaction-id="${added.id}"]`),
    ).toHaveTextContent("Observed event");
  });
  expect(ui.getByRole("checkbox")).not.toBeChecked();
  expect(ui.getByRole("button", { name: "Confirm History" })).toBeDisabled();
});
