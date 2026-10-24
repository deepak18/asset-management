import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { RouteHarness } from "./route-harness";
import {
  PortfolioSelectionProvider,
  usePortfolioSelection,
} from "@/hooks/use-portfolio-selection";
import { apiClient } from "@/lib/api-client";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { demoPreview, demoRetirementCsv } from "@/mocks/retirement-fixtures";
import { retirementTransport } from "../lib/retirement-transport";

const base = `${env.apiBaseUrl}/api/v1/portfolios`;
const nav = () =>
  within(screen.getByRole("navigation", { name: "Primary navigation" }));
beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("am.selected.portfolio", "1");
  window.history.replaceState(null, "", "/");
});
afterEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});
function Probe() {
  const { dataVersion } = usePortfolioSelection();
  return <output aria-label="Data version">{dataVersion}</output>;
}
function mount(path: string) {
  window.history.replaceState(null, "", path);
  return render(
    <PortfolioSelectionProvider>
      <Probe />
      <RouteHarness />
    </PortfolioSelectionProvider>,
  );
}
function noImports() {
  expect(screen.queryByLabelText("Vanguard CSV")).toBeNull();
  expect(screen.queryByLabelText("Upload Broker Statement")).toBeNull();
  expect(screen.queryByRole("button", { name: "Edit Account Settings" })).toBeNull();
}

it.each([
  ["Reported Holdings", "Reported Holdings"],
  ["Imports", "Statement Imports"],
  ["Account Settings", "Account Settings"],
  ["Overview", "Account Overview"],
])(
  "navigates to %s under persistent active navigation and retains picker/theme identity",
  async (name, heading) => {
    const user = userEvent.setup();
    mount("/holdings?portfolio=3");
    await screen.findByText(/No reported snapshot yet/);
    const header = screen.getByRole("banner");
    const picker = screen.getByRole("combobox", { name: "Select portfolio" });
    expect(picker).toHaveValue("3");
    expect(nav().getByRole("link", { name: "Reported Holdings" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    noImports();
    await user.click(screen.getByRole("button", { name: "Toggle Theme" }));

    await user.click(nav().getByRole("link", { name }));
    await screen.findByRole("heading", { level: 1, name: heading });
    expect(screen.getByRole("banner")).toBe(header);
    expect(screen.getByRole("combobox", { name: "Select portfolio" })).toBe(picker);
    expect(picker).toHaveValue("3");
    expect(nav().getByRole("link", { name })).toHaveAttribute("aria-current", "page");
    expect(document.documentElement).toHaveClass("dark");
    expect(window.localStorage.getItem("am.selected.portfolio")).toBe("3");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute(
      "href",
      "#main-content",
    );
  },
);

it.each(["/holdings", "/ledger"])(
  "directly mounts %s without either import form or account settings",
  async (path) => {
    mount(path);
    await screen.findByRole("heading", { level: 1 });
    if (path === "/holdings") await screen.findByText(/No reported snapshot yet/);
    else await screen.findByRole("button", { name: "Edit AAPL Sector" });
    noImports();
  },
);

it("mounts only one brokerage form and resets Vanguard drafts/review on brokerage and account switches", async () => {
  const user = userEvent.setup();
  mount("/imports?portfolio=99");
  const brokerage = await screen.findByRole("combobox", { name: "Brokerage" });
  expect(screen.getByLabelText("Upload Broker Statement")).toBeInTheDocument();
  expect(screen.queryByLabelText("Vanguard CSV")).toBeNull();
  await user.selectOptions(brokerage, "vanguard");
  expect(screen.queryByLabelText("Upload Broker Statement")).toBeNull();
  expect(screen.getByLabelText("Vanguard CSV")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Holdings as of date"), {
    target: { value: "2026-10-20" },
  });
  await user.selectOptions(brokerage, "robinhood");
  await user.selectOptions(brokerage, "vanguard");
  expect(screen.getByLabelText("Holdings as of date")).toHaveValue("");
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Select portfolio" }),
    "1",
  );
  expect(await screen.findByRole("combobox", { name: "Brokerage" })).toHaveValue(
    "robinhood",
  );
  expect(screen.queryByLabelText("Vanguard CSV")).toBeNull();
});

it.each(["brokerage", "account", "route"])(
  "aborts an abandoned Vanguard preview on %s change without refreshing the new scope",
  async (change) => {
    retirementTransport();
    const user = userEvent.setup();
    let release!: () => void;
    let signal: AbortSignal | undefined;
    server.use(
      http.post(`${base}/99/retirement-imports/preview`, async ({ request }) => {
        signal = request.signal;
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        return HttpResponse.json(
          demoPreview(99, {
            as_of: "2026-10-20",
            currency: "USD",
            history_complete: false,
          }),
        );
      }),
    );
    mount("/imports?portfolio=99");
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Brokerage" }),
      "vanguard",
    );
    await user.upload(
      screen.getByLabelText("Vanguard CSV"),
      new File([demoRetirementCsv], "demo-retirement.csv", { type: "text/csv" }),
    );
    fireEvent.change(screen.getByLabelText("Holdings as of date"), {
      target: { value: "2026-10-20" },
    });
    await user.click(screen.getByRole("button", { name: "Preview Vanguard Import" }));
    await waitFor(() => expect(signal).toBeDefined());
    if (change === "brokerage")
      await user.selectOptions(
        screen.getByRole("combobox", { name: "Brokerage" }),
        "robinhood",
      );
    else if (change === "account")
      await user.selectOptions(
        screen.getByRole("combobox", { name: "Select portfolio" }),
        "1",
      );
    else await user.click(nav().getByRole("link", { name: "Ledger Analytics" }));
    expect(signal?.aborted).toBe(true);
    await act(async () => release());
    expect(screen.queryByRole("region", { name: "Vanguard preview" })).toBeNull();
    expect(screen.getByLabelText("Data version")).toHaveTextContent("0");
  },
);

it("saves Taxable Brokerage using the existing TAXABLE value and refreshes shared metadata on the settings route", async () => {
  const user = userEvent.setup();
  const patch = vi.spyOn(apiClient, "updateAccount");
  mount("/settings?portfolio=99");
  await user.click(
    await screen.findByRole("button", { name: "Edit Account Settings" }),
  );
  const type = screen.getByRole("combobox", { name: "Account type" });
  expect(screen.getByRole("option", { name: "Taxable Brokerage" })).toHaveValue(
    "TAXABLE",
  );
  expect(type).toHaveAccessibleDescription(/ordinary, non-retirement/);
  await user.selectOptions(type, "TAXABLE");
  await user.click(screen.getByRole("button", { name: "Save Account Settings" }));
  expect(await screen.findByText("Account settings saved.")).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByLabelText("Data version")).toHaveTextContent("1"),
  );
  expect(patch).toHaveBeenCalledWith(
    99,
    expect.objectContaining({ account_type: "TAXABLE" }),
    expect.any(AbortSignal),
  );
  expect((await apiClient.getPortfolio(99)).account_type).toBe("TAXABLE");
  expect(
    await screen.findByText("Taxable Brokerage", { exact: true }),
  ).toBeInTheDocument();
});

it("reconciles same-route query navigation without reapplying an old query after picker changes", async () => {
  const user = userEvent.setup();
  mount("/holdings?portfolio=99");
  await screen.findByText(/No reported snapshot yet/);
  await act(async () => {
    window.history.pushState(null, "", "/holdings?portfolio=3");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "Select portfolio" })).toHaveValue("3"),
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Select portfolio" }),
    "1",
  );
  expect(screen.getByRole("combobox", { name: "Select portfolio" })).toHaveValue("1");
  await user.click(nav().getByRole("link", { name: "Ledger Analytics" }));
  expect(
    await screen.findByRole("button", { name: "Edit AAPL Sector" }),
  ).toBeInTheDocument();
  expect(window.location.search).toBe("?portfolio=1");
});
it("keeps holding-detail navigation scoped to its URL portfolio rather than the picker", async () => {
  mount("/portfolios/3/holdings/PLTR");
  await screen.findByRole("combobox", { name: "Select portfolio" });
  expect(nav().getByRole("link", { name: "Ledger Analytics" })).toHaveAttribute(
    "href",
    "/ledger?portfolio=3",
  );
  expect(nav().getByRole("link", { name: "Ledger Analytics" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});
it("refreshes shared data and Robinhood history on async success and links to the resulting ledger", async () => {
  const user = userEvent.setup();
  const { createImport } = await import("@/mocks/state");
  const result = createImport(1, "route-history.csv", 100, true);
  if (!result.ok) throw new Error("Fixture import refused");
  const job = result.job;
  let historyReads = 0;
  server.use(
    http.post(`${base}/1/imports`, () => HttpResponse.json(job, { status: 202 })),
    http.get(`${base}/1/imports/${job.id}`, () =>
      HttpResponse.json({ ...job, status: "SUCCEEDED", created_transactions: 3 }),
    ),
    http.get(`${base}/1/imports`, () => {
      historyReads += 1;
      return HttpResponse.json([
        { ...job, status: historyReads > 1 ? "SUCCEEDED" : "PENDING" },
      ]);
    }),
  );
  mount("/imports?portfolio=1");
  await screen.findByRole("combobox", { name: "Brokerage" });
  await user.upload(
    screen.getByLabelText("Upload Broker Statement"),
    new File(["Activity Date,Instrument"], "route-history.csv", { type: "text/csv" }),
  );
  const link = await screen.findByRole(
    "link",
    { name: "View Ledger Analytics" },
    { timeout: 3000 },
  );
  expect(link).toHaveAttribute("href", "/ledger?portfolio=1");
  expect(screen.getByLabelText("Data version")).toHaveTextContent("1");
  await waitFor(() => expect(historyReads).toBeGreaterThan(1));
  await user.click(link);
  expect(
    await screen.findByRole("button", { name: "Edit AAPL Sector" }),
  ).toBeInTheDocument();
  noImports();
});
it.each(["brokerage", "account", "route"])(
  "isolates a late Robinhood upload after %s change",
  async (change) => {
    const user = userEvent.setup();
    const { createImport } = await import("@/mocks/state");
    const result = createImport(1, "late.csv", 100, true);
    if (!result.ok) throw new Error("Fixture import refused");
    let release!: () => void;
    let started = false;
    server.use(
      http.post(`${base}/1/imports`, async () => {
        started = true;
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        return HttpResponse.json(
          { ...result.job, status: "SUCCEEDED" },
          { status: 202 },
        );
      }),
    );
    mount("/imports?portfolio=1");
    await screen.findByRole("combobox", { name: "Brokerage" });
    await user.upload(
      screen.getByLabelText("Upload Broker Statement"),
      new File(["Activity Date,Instrument"], "late.csv", { type: "text/csv" }),
    );
    await waitFor(() => expect(started).toBe(true));
    if (change === "brokerage")
      await user.selectOptions(
        screen.getByRole("combobox", { name: "Brokerage" }),
        "vanguard",
      );
    else if (change === "account")
      await user.selectOptions(
        screen.getByRole("combobox", { name: "Select portfolio" }),
        "99",
      );
    else await user.click(nav().getByRole("link", { name: "Reported Holdings" }));
    await act(async () => release());
    expect(screen.getByLabelText("Data version")).toHaveTextContent("0");
    expect(screen.queryByRole("link", { name: "View Ledger Analytics" })).toBeNull();
  },
);
it("surfaces Robinhood API errors on imports only, then resets them on a brokerage change", async () => {
  const user = userEvent.setup();
  server.use(
    http.post(`${base}/1/imports`, () =>
      HttpResponse.json({ detail: "Review this duplicate export" }, { status: 409 }),
    ),
  );
  mount("/imports?portfolio=1");
  await screen.findByRole("combobox", { name: "Brokerage" });
  await user.upload(
    screen.getByLabelText("Upload Broker Statement"),
    new File(["Activity Date,Instrument"], "duplicate.csv", { type: "text/csv" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Review this duplicate export",
  );
  expect(screen.getByRole("button", { name: "Import Anyway" })).toBeInTheDocument();
  expect(screen.getByLabelText("Data version")).toHaveTextContent("0");
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Brokerage" }),
    "vanguard",
  );
  expect(screen.queryByText("Review this duplicate export")).toBeNull();
  expect(screen.queryByRole("button", { name: "Import Anyway" })).toBeNull();
});
it("announces route-boundary loading before mounting account forms", async () => {
  let release!: () => void;
  server.use(
    http.get(base, async () => {
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return HttpResponse.json([]);
    }),
  );
  mount("/imports");
  expect(
    within(screen.getByRole("main")).getAllByRole("status", { name: "Loading" })[0],
  ).toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "Brokerage" })).toBeNull();
  await waitFor(() => expect(release).toBeTypeOf("function"));
  await act(async () => release());
  expect(await screen.findByText("No portfolios yet")).toBeInTheDocument();
});
it("shows a creation action rather than fabricated account data for an empty list", async () => {
  server.use(http.get(base, () => HttpResponse.json([])));
  mount("/holdings");
  expect(await screen.findByText("No portfolios yet")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Create Portfolio" })).toHaveLength(2);
  expect(screen.queryByText(/USD 0.00/)).toBeNull();
});
it("announces portfolio-list failures without mounting a write form", async () => {
  server.use(
    http.get(base, () =>
      HttpResponse.json({ detail: "Service unavailable" }, { status: 500 }),
    ),
  );
  mount("/settings");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not load your portfolios.",
  );
  expect(screen.queryByRole("button", { name: "Edit Account Settings" })).toBeNull();
});
it("reports selector reload failure without hiding successful settings or retargeting the account", async () => {
  const user = userEvent.setup();
  mount("/settings?portfolio=99");
  await user.click(
    await screen.findByRole("button", { name: "Edit Account Settings" }),
  );
  await user.type(screen.getByLabelText("Account ID"), "000042");
  server.use(
    http.get(base, () =>
      HttpResponse.json({ detail: "List unavailable" }, { status: 500 }),
    ),
  );
  await user.click(screen.getByRole("button", { name: "Save Account Settings" }));
  expect(await screen.findByText("Account settings saved.")).toBeInTheDocument();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Portfolio selector could not refresh",
  );
  expect(await screen.findByText("000042", { exact: true })).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Select portfolio" })).toHaveValue("99");
});
