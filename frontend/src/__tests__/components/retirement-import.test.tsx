import * as React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { RetirementImportPanel } from "@/components/portfolio/retirement-import-panel";
import { Dashboard } from "@/components/portfolio/dashboard";
import {
  PortfolioSelectionProvider,
  usePortfolioSelection,
} from "@/hooks/use-portfolio-selection";
import { server } from "@/mocks/server";
import { env } from "@/lib/env";
import { apiClient } from "@/lib/api-client";
import { demoPreview, demoRetirementCsv } from "@/mocks/retirement-fixtures";
import { retirementTransport } from "../lib/retirement-transport";

const base = `${env.apiBaseUrl}/api/v1`;
const options = { as_of: "2026-10-20", currency: "USD", history_complete: false };
afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

async function choose(user: ReturnType<typeof userEvent.setup>) {
  const file = new File([demoRetirementCsv], "demo-retirement.csv", {
    type: "text/csv",
  });
  await user.upload(screen.getByLabelText("Vanguard CSV"), file);
  fireEvent.change(screen.getByLabelText("Holdings as of date"), {
    target: { value: options.as_of },
  });
  return file;
}
async function preview(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Preview Vanguard Import" }));
  return screen.findByRole("region", { name: "Vanguard preview" });
}
async function acknowledge(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    screen.getByRole("checkbox", {
      name: "I reviewed the source account, holdings, activity and issues",
    }),
  );
}

it("previews and explicitly confirms a real multipart mock import, refreshing the primary reported view, metadata, history and activity", async () => {
  retirementTransport();
  const user = userEvent.setup();
  window.localStorage.setItem("am.selected.portfolio", "99");
  function SelectionProbe() {
    const selection = usePortfolioSelection();
    return (
      <output aria-label="Selected account ID">
        {selection.selected?.external_account_id ?? "unbound"}
      </output>
    );
  }
  render(
    <PortfolioSelectionProvider>
      <SelectionProbe />
      <Dashboard />
    </PortfolioSelectionProvider>,
  );
  const previewButton = await screen.findByRole("button", {
    name: "Preview Vanguard Import",
  });
  expect(previewButton).toBeDisabled();
  expect(screen.getByLabelText("Holdings as of date")).toHaveValue("");
  await choose(user);
  const review = within(await preview(user));
  expect(review.getByText(/Source account 000042/)).toHaveTextContent(
    "Fictional Example Plan",
  );
  expect(review.getByRole("table", { name: "Preview holdings" })).toHaveTextContent(
    "12.3456789012",
  );
  expect(review.getByRole("table", { name: "Preview holdings" })).toHaveTextContent(
    "USD 247.05",
  );
  expect(review.getByText(/Will create UNKNOWN security/)).toHaveTextContent(
    "No confirmed ticker",
  );
  expect(review.getByText(/Incomplete history:/)).toBeInTheDocument();
  await user.click(review.getByText("Inspect activity (1)"));
  expect(review.getByRole("table", { name: "Source activity" })).toHaveTextContent(
    "114001",
  );
  expect(review.getByRole("table", { name: "Share reconciliation" })).toHaveTextContent(
    "11.1116789012",
  );
  expect(
    screen.getByRole("button", { name: "Confirm Vanguard Import" }),
  ).toBeDisabled();
  await acknowledge(user);
  await user.click(screen.getByRole("button", { name: "Confirm Vanguard Import" }));
  expect(await screen.findByText(/Vanguard import committed/)).toBeInTheDocument();
  expect(
    await screen.findByRole("table", { name: "Reported holdings" }),
  ).toHaveTextContent("Example Balanced Trust");
  expect(screen.getByText("Reported balance")).toHaveTextContent("USD 247.05");
  expect(screen.queryByText("USD 0.00")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reported Holdings" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.queryByText("Allocation by sector")).not.toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByLabelText("Selected account ID")).toHaveTextContent("000042"),
  );
  expect(await screen.findByText("Vanguard", { exact: true })).toBeInTheDocument();
  expect(await screen.findByText(/Persisted account activity: 1/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Confirm Vanguard Import" }),
  ).not.toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "Inspect Import #901" }));
  expect(
    await screen.findByRole("region", { name: "Vanguard preview" }),
  ).toHaveTextContent("Source account 000042");
  expect(await apiClient.listTransactions(99)).toEqual([]);
  await user.click(screen.getByRole("button", { name: "Preview Vanguard Import" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("already imported");
  expect(screen.getByLabelText("Holdings as of date")).toHaveValue(options.as_of);
});

it("requires an explicit date and discards reviews on date, history and file changes; blocking issues prohibit confirmation", async () => {
  retirementTransport();
  const user = userEvent.setup();
  render(
    <RetirementImportPanel portfolioId={99} refreshToken={0} onSuccess={vi.fn()} />,
  );
  await user.upload(
    screen.getByLabelText("Vanguard CSV"),
    new File([demoRetirementCsv], "demo-retirement.csv", { type: "text/csv" }),
  );
  expect(
    screen.getByRole("button", { name: "Preview Vanguard Import" }),
  ).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Holdings as of date"), {
    target: { value: options.as_of },
  });
  await preview(user);
  await acknowledge(user);
  fireEvent.change(screen.getByLabelText("Holdings as of date"), {
    target: { value: "2026-10-21" },
  });
  expect(
    screen.queryByRole("region", { name: "Vanguard preview" }),
  ).not.toBeInTheDocument();
  await preview(user);
  await user.click(
    screen.getByRole("checkbox", { name: "Includes All Transactions Since Inception" }),
  );
  expect(
    screen.queryByRole("button", { name: "Confirm Vanguard Import" }),
  ).not.toBeInTheDocument();
  server.use(
    http.post(`${base}/portfolios/99/retirement-imports/preview`, () =>
      HttpResponse.json({
        ...demoPreview(99, options),
        can_commit: false,
        issues: [
          {
            code: "UNSUPPORTED_ACTIVITY",
            blocking: true,
            source_line: 8,
            message: "Unknown activity code needs review",
          },
        ],
      }),
    ),
  );
  const review = within(await preview(user));
  expect(review.getByText(/Blocking.*Unknown activity/)).toHaveTextContent(
    "Source line 8",
  );
  await acknowledge(user);
  expect(
    screen.getByRole("button", { name: "Confirm Vanguard Import" }),
  ).toBeDisabled();
  await user.upload(
    screen.getByLabelText("Vanguard CSV"),
    new File(["other fictional bytes"], "other.csv", { type: "text/csv" }),
  );
  expect(
    screen.queryByRole("region", { name: "Vanguard preview" }),
  ).not.toBeInTheDocument();
});

it.each([
  "Duplicate file: inspect existing import",
  "Overlapping source events: combine nonoverlapping periods",
])(
  "shows actionable 409 %s and preserves upload drafts while requiring a new preview",
  async (detail) => {
    retirementTransport();
    const user = userEvent.setup();
    const changed = vi.fn();
    let commits = 0;
    server.use(
      http.post(`${base}/portfolios/99/retirement-imports`, () => {
        commits += 1;
        return HttpResponse.json({ detail }, { status: 409 });
      }),
    );
    render(
      <RetirementImportPanel portfolioId={99} refreshToken={0} onSuccess={changed} />,
    );
    const file = await choose(user);
    await preview(user);
    await acknowledge(user);
    await user.click(screen.getByRole("button", { name: "Confirm Vanguard Import" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
    expect(screen.getByRole("alert")).toHaveTextContent("Create a new preview");
    expect(
      screen.queryByRole("button", { name: "Confirm Vanguard Import" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Holdings as of date")).toHaveValue(options.as_of);
    expect((screen.getByLabelText("Vanguard CSV") as HTMLInputElement).files?.[0]).toBe(
      file,
    );
    expect(commits).toBe(1);
    expect(changed).not.toHaveBeenCalled();
    await preview(user);
    expect(screen.getByRole("checkbox", { name: /I reviewed/ })).not.toBeChecked();
  },
);

it.each([413, 422, 500])(
  "keeps upload drafts and backend error on %s",
  async (status) => {
    const user = userEvent.setup();
    server.use(
      http.post(`${base}/portfolios/99/retirement-imports/preview`, () =>
        HttpResponse.json({ detail: "Fix the source export" }, { status }),
      ),
    );
    render(
      <RetirementImportPanel portfolioId={99} refreshToken={0} onSuccess={vi.fn()} />,
    );
    const file = await choose(user);
    await user.click(screen.getByRole("button", { name: "Preview Vanguard Import" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Fix the source export");
    expect((screen.getByLabelText("Vanguard CSV") as HTMLInputElement).files?.[0]).toBe(
      file,
    );
    expect(screen.getByLabelText("Holdings as of date")).toHaveValue(options.as_of);
  },
);

it("cancels a pending preview and ignores late preview/history responses after portfolio switching", async () => {
  retirementTransport();
  const user = userEvent.setup();
  let release!: () => void;
  let signal: AbortSignal | undefined;
  server.use(
    http.post(
      `${base}/portfolios/99/retirement-imports/preview`,
      async ({ request }) => {
        signal = request.signal;
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        return HttpResponse.json(demoPreview(99, options));
      },
    ),
  );
  const changed = vi.fn();
  const view = render(
    <RetirementImportPanel portfolioId={99} refreshToken={0} onSuccess={changed} />,
  );
  await choose(user);
  await user.click(screen.getByRole("button", { name: "Preview Vanguard Import" }));
  await waitFor(() => expect(signal).toBeDefined());
  await user.click(screen.getByRole("button", { name: "Cancel Vanguard Review" }));
  expect(signal?.aborted).toBe(true);
  await act(async () => release());
  expect(
    screen.queryByRole("region", { name: "Vanguard preview" }),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("Holdings as of date")).toHaveValue(options.as_of);
  let releaseHistory!: () => void;
  let historySignal: AbortSignal | undefined;
  server.use(
    http.get(`${base}/portfolios/99/retirement-imports`, async ({ request }) => {
      historySignal = request.signal;
      await new Promise<void>((resolve) => {
        releaseHistory = resolve;
      });
      return HttpResponse.json([
        {
          id: 777,
          portfolio_id: 99,
          valuation_id: 1,
          imported_at: "2026-10-22T00:00:00Z",
          storage_key: "fictional",
          status: "COMMITTED",
          preview: demoPreview(99, options),
        },
      ]);
    }),
  );
  await user.click(screen.getByRole("button", { name: "Reload Retirement History" }));
  await waitFor(() => expect(historySignal).toBeDefined());
  view.rerender(
    <RetirementImportPanel portfolioId={1} refreshToken={0} onSuccess={changed} />,
  );
  await act(async () => releaseHistory());
  expect(historySignal?.aborted).toBe(true);
  expect(
    screen.queryByRole("button", { name: "Inspect Import #777" }),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("Holdings as of date")).toHaveValue("");
  expect(changed).not.toHaveBeenCalled();
});

it("aborts a pending commit on unmount and never refreshes an abandoned portfolio or double-submits", async () => {
  retirementTransport();
  const user = userEvent.setup();
  let release!: () => void;
  let signal: AbortSignal | undefined;
  let commits = 0;
  const changed = vi.fn();
  server.use(
    http.post(`${base}/portfolios/99/retirement-imports`, async ({ request }) => {
      commits += 1;
      signal = request.signal;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return HttpResponse.json(
        {
          id: 901,
          portfolio_id: 99,
          valuation_id: 801,
          imported_at: "2026-10-22T00:00:00Z",
          storage_key: "fictional",
          status: "COMMITTED",
          preview: demoPreview(99, options),
        },
        { status: 201 },
      );
    }),
  );
  const view = render(
    <RetirementImportPanel portfolioId={99} refreshToken={0} onSuccess={changed} />,
  );
  await choose(user);
  await preview(user);
  await acknowledge(user);
  await user.dblClick(screen.getByRole("button", { name: "Confirm Vanguard Import" }));
  await waitFor(() => expect(signal).toBeDefined());
  view.unmount();
  await act(async () => release());
  expect(signal?.aborted).toBe(true);
  expect(commits).toBe(1);
  expect(changed).not.toHaveBeenCalled();
});

it("invalidates a sibling-write review without resetting upload drafts", async () => {
  retirementTransport();
  const user = userEvent.setup();
  const view = render(
    <RetirementImportPanel portfolioId={99} refreshToken={0} onSuccess={vi.fn()} />,
  );
  await choose(user);
  await preview(user);
  await acknowledge(user);
  view.rerender(
    <RetirementImportPanel portfolioId={99} refreshToken={1} onSuccess={vi.fn()} />,
  );
  expect(
    screen.queryByRole("button", { name: "Confirm Vanguard Import" }),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("Holdings as of date")).toHaveValue(options.as_of);
  await preview(user);
  expect(screen.getByRole("checkbox", { name: /I reviewed/ })).not.toBeChecked();
});

it("recovers failed history reads and preserves the loaded review after a retryable commit error", async () => {
  retirementTransport();
  const user = userEvent.setup();
  const changed = vi.fn();
  let historyReads = 0;
  let commits = 0;
  server.use(
    http.get(`${base}/portfolios/99/retirement-imports`, () => {
      historyReads += 1;
      return historyReads === 1
        ? HttpResponse.json(
            { detail: "History temporarily unavailable" },
            { status: 500 },
          )
        : HttpResponse.json([]);
    }),
    http.post(`${base}/portfolios/99/retirement-imports`, () => {
      commits += 1;
      return HttpResponse.json(
        { detail: "Please correct the export" },
        { status: 422 },
      );
    }),
  );
  render(
    <RetirementImportPanel portfolioId={99} refreshToken={0} onSuccess={changed} />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "History temporarily unavailable",
  );
  await user.click(screen.getByRole("button", { name: "Reload Retirement History" }));
  expect(await screen.findByText("No Vanguard imports yet.")).toBeInTheDocument();
  await choose(user);
  await preview(user);
  await acknowledge(user);
  await user.click(screen.getByRole("button", { name: "Confirm Vanguard Import" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Please correct the export",
  );
  expect(screen.getByRole("region", { name: "Vanguard preview" })).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /I reviewed/ })).toBeChecked();
  expect(screen.getByLabelText("Holdings as of date")).toHaveValue(options.as_of);
  expect(screen.getByRole("button", { name: "Confirm Vanguard Import" })).toBeEnabled();
  expect(commits).toBe(1);
  expect(changed).not.toHaveBeenCalled();
});
