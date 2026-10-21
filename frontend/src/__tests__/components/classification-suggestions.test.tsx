import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { HoldingDetail } from "@/components/portfolio/holding-detail";
import { HoldingClassificationCell } from "@/components/portfolio/holding-classification-cell";
import { classificationSuggestions } from "@/components/portfolio/classification-combobox";
import { Dialog } from "@/components/ui/dialog";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { holdings } from "@/mocks/fixtures";
import type { HoldingClassificationUpdate, HoldingInfo } from "@/types/domain";

const base = `${env.apiBaseUrl}/api/v1/portfolios`;
const current: HoldingInfo = {
  ...holdings[0]!,
  sector: "Current Sector",
  industry: "Current Industry",
};
const rows: HoldingInfo[] = [
  current,
  { ...current, ticker: "MSFT", sector: "  Energy  ", industry: " Software " },
  { ...current, ticker: "NVDA", sector: "energy", industry: "software" },
  { ...current, ticker: "XYZ", sector: "Banking", industry: "Energy Services" },
  { ...current, ticker: "EMPTY", sector: null, industry: "  " },
];

function mockRows() {
  const reads = vi.fn();
  server.use(
    http.get(`${base}/1/holdings`, () => {
      reads();
      return HttpResponse.json(rows);
    }),
    http.get(`${base}/1/holdings/AAPL`, () => HttpResponse.json(current)),
  );
  return reads;
}

function deferred() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

it("normalizes, deduplicates and sorts each field independently, retaining the first spelling", () => {
  expect(classificationSuggestions(rows)).toEqual({
    sector: ["Banking", "Current Sector", "Energy"],
    industry: ["Current Industry", "Energy Services", "Software"],
  });
  expect(classificationSuggestions([])).toEqual({ sector: [], industry: [] });
});

describe.each(["table", "detail"] as const)("%s suggestions", (view) => {
  function mount(portfolioId = 1, refreshToken = 0) {
    return view === "table" ? (
      <HoldingsTable portfolioId={portfolioId} refreshToken={refreshToken} />
    ) : (
      <HoldingDetail portfolioId={portfolioId} ticker="AAPL" />
    );
  }

  it("uses other holdings of the same field, includes the current value, filters substrings, and shares one read", async () => {
    const reads = mockRows();
    const user = userEvent.setup();
    render(mount());
    await user.click(await screen.findByRole("button", { name: "Edit AAPL Sector" }));
    const sector = screen.getByRole("combobox", { name: "AAPL sector" });
    await user.clear(sector);
    expect(
      (await screen.findAllByRole("option")).map((node) => node.textContent),
    ).toEqual(["Banking", "Current Sector", "Energy"]);
    expect(sector).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById(sector.getAttribute("aria-controls")!)).toHaveRole(
      "listbox",
    );
    await user.type(sector, "eNeR");
    expect(screen.getAllByRole("option").map((node) => node.textContent)).toEqual([
      "Energy",
    ]);
    await user.click(screen.getByRole("option", { name: "Energy" }));
    expect(sector).toHaveValue("Energy");
    expect(sector).toHaveFocus();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save AAPL Sector" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Edit AAPL Industry" }));
    const industry = screen.getByRole("combobox", { name: "AAPL industry" });
    await user.clear(industry);
    expect(screen.getAllByRole("option").map((node) => node.textContent)).toEqual([
      "Current Industry",
      "Energy Services",
      "Software",
    ]);
    expect(screen.queryByRole("option", { name: "Banking" })).not.toBeInTheDocument();
    expect(reads).toHaveBeenCalledTimes(1);
  });

  it("refreshes options after saving free text while preserving an open sibling draft", async () => {
    const user = userEvent.setup();
    let saved = false;
    const bodies: HoldingClassificationUpdate[] = [];
    server.use(
      http.get(`${base}/1/holdings`, () =>
        HttpResponse.json(
          saved
            ? [
                { ...current, sector: "New Sector" },
                { ...rows[1]!, industry: "Refreshed Industry" },
              ]
            : rows,
        ),
      ),
      http.get(`${base}/1/holdings/AAPL`, () =>
        HttpResponse.json({
          ...current,
          sector: saved ? "New Sector" : current.sector,
        }),
      ),
      http.patch(`${base}/1/holdings/AAPL`, async ({ request }) => {
        bodies.push((await request.json()) as HoldingClassificationUpdate);
        saved = true;
        return HttpResponse.json({
          ...current,
          sector: "New Sector",
          classification_source: "MANUAL",
        });
      }),
    );
    render(mount());
    await user.click(await screen.findByRole("button", { name: "Edit AAPL Industry" }));
    const industry = screen.getByRole("combobox", { name: "AAPL industry" });
    await user.clear(industry);
    await user.type(industry, "Keep draft");
    await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
    const sector = screen.getByRole("combobox", { name: "AAPL sector" });
    await user.clear(sector);
    await user.type(sector, "  New Sector  ");
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save AAPL Sector" }));
    await screen.findByRole("button", { name: "Edit AAPL Sector" });
    expect(bodies).toEqual([{ sector: "New Sector" }]);
    expect(industry).toHaveValue("Keep draft");
    await user.clear(industry);
    expect(
      await screen.findByRole("option", { name: "Refreshed Industry" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
    const reopened = screen.getByRole("combobox", { name: "AAPL sector" });
    await user.clear(reopened);
    expect(
      await screen.findByRole("option", { name: "New Sector" }),
    ).toBeInTheDocument();
  });

  it("discards delayed same-field suggestions after a portfolio switch", async () => {
    const gate = deferred();
    const started = vi.fn();
    const finished = vi.fn();
    server.use(
      http.get(`${base}/1/holdings`, async () => {
        started();
        await gate.promise;
        finished();
        return HttpResponse.json([{ ...current, sector: "Old Portfolio Only" }]);
      }),
      http.get(`${base}/2/holdings`, () =>
        HttpResponse.json([
          { ...current, sector: null },
          { ...current, ticker: "MSFT", sector: "New Portfolio Only" },
        ]),
      ),
      http.get(`${base}/2/holdings/AAPL`, () =>
        HttpResponse.json({ ...current, sector: null }),
      ),
    );
    const user = userEvent.setup();
    const { rerender } = render(mount());
    await waitFor(() => expect(started).toHaveBeenCalled());
    rerender(mount(2));
    await user.click(await screen.findByRole("button", { name: "Edit AAPL Sector" }));
    await user.clear(screen.getByRole("combobox"));
    expect(
      await screen.findByRole("option", { name: "New Portfolio Only" }),
    ).toBeInTheDocument();
    await act(async () => {
      gate.release();
      await gate.promise;
    });
    await waitFor(() => expect(finished).toHaveBeenCalled());
    expect(
      screen.queryByRole("option", { name: "Old Portfolio Only" }),
    ).not.toBeInTheDocument();
  });
});

it("supports keyboard selection without submitting, unique IDs, blur/outside dismissal and modal-safe Escape", async () => {
  const user = userEvent.setup();
  const changed = vi.fn();
  const close = vi.fn();
  render(
    <Dialog open onClose={close} title="Classification Test">
      <HoldingClassificationCell
        portfolioId={1}
        holding={current}
        field="sector"
        suggestions={["Banking", "Current Sector", "Energy"]}
        onChanged={changed}
      />
      <HoldingClassificationCell
        portfolioId={1}
        holding={current}
        field="industry"
        suggestions={["Current Industry", "Software"]}
        onChanged={changed}
      />
      <button type="button">Outside</button>
    </Dialog>,
  );
  await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
  const sector = screen.getByRole("combobox", { name: "AAPL sector" });
  await user.clear(sector);
  const firstId = sector.getAttribute("aria-controls");
  await user.keyboard("{ArrowUp}");
  expect(
    document.getElementById(sector.getAttribute("aria-activedescendant")!),
  ).toHaveTextContent("Energy");
  await user.keyboard("{ArrowDown}");
  expect(
    document.getElementById(sector.getAttribute("aria-activedescendant")!),
  ).toHaveTextContent("Banking");
  await user.keyboard("{Enter}");
  expect(sector).toHaveValue("Banking");
  expect(changed).not.toHaveBeenCalled();
  await user.clear(sector);
  await user.keyboard("{Enter}");
  expect(changed).not.toHaveBeenCalled();
  await user.keyboard("{ArrowDown}{Escape}");
  expect(close).not.toHaveBeenCalled();
  expect(sector).toHaveAttribute("aria-expanded", "false");
  expect(sector).not.toHaveAttribute("aria-activedescendant");
  await user.click(sector);
  await user.tab();
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  await user.click(sector);
  await user.click(screen.getByRole("button", { name: "Outside" }));
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Edit AAPL Industry" }));
  const industry = screen.getByRole("combobox", { name: "AAPL industry" });
  expect(industry.getAttribute("aria-controls")).not.toBe(firstId);
  expect(within(screen.getByRole("listbox")).getByRole("option")).toHaveTextContent(
    "Current Industry",
  );
  expect(sector).toHaveValue("");
});

it("keeps free-text editing available during a failed detail suggestions read and retains failed PATCH drafts", async () => {
  const gate = deferred();
  server.use(
    http.get(`${base}/1/holdings`, async () => {
      await gate.promise;
      return HttpResponse.json({ detail: "Unavailable" }, { status: 500 });
    }),
    http.patch(`${base}/1/holdings/AAPL`, () =>
      HttpResponse.json({ detail: "Validation failed" }, { status: 422 }),
    ),
  );
  const user = userEvent.setup();
  render(<HoldingDetail portfolioId={1} ticker="AAPL" />);
  await user.click(await screen.findByRole("button", { name: "Edit AAPL Sector" }));
  const input = screen.getByRole("combobox");
  await user.clear(input);
  await user.type(input, "Personal Label");
  expect(screen.getByText(/Loading classification suggestions/)).toBeInTheDocument();
  await act(async () => {
    gate.release();
    await gate.promise;
  });
  expect(
    await screen.findByText(/Portfolio suggestions unavailable/),
  ).toBeInTheDocument();
  expect(input).toHaveValue("Personal Label");
  await user.click(screen.getByRole("button", { name: "Save AAPL Sector" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Validation failed");
  expect(input).toHaveValue("Personal Label");
  expect(input).toHaveAttribute("aria-invalid", "true");
});

it("cancels without PATCH and sends exactly null for a blank clear after selecting an option", async () => {
  const user = userEvent.setup();
  const changed = vi.fn();
  const bodies: HoldingClassificationUpdate[] = [];
  server.use(
    http.patch(`${base}/1/holdings/AAPL`, async ({ request }) => {
      bodies.push((await request.json()) as HoldingClassificationUpdate);
      return HttpResponse.json({ ...current, sector: null });
    }),
  );
  render(
    <HoldingClassificationCell
      portfolioId={1}
      holding={current}
      field="sector"
      suggestions={["Energy"]}
      onChanged={changed}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
  await user.clear(screen.getByRole("combobox"));
  await user.click(screen.getByRole("option", { name: "Energy" }));
  expect(bodies).toEqual([]);
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(bodies).toEqual([]);
  await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
  await user.clear(screen.getByRole("combobox"));
  await user.type(screen.getByRole("combobox"), "  ");
  await user.click(screen.getByRole("button", { name: "Save AAPL Sector" }));
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(bodies).toEqual([{ sector: null }]);
});

it("refreshes table suggestions on external refresh without discarding a draft", async () => {
  mockRows();
  const user = userEvent.setup();
  const { rerender } = render(<HoldingsTable portfolioId={1} />);
  await user.click(await screen.findByRole("button", { name: "Edit AAPL Sector" }));
  const input = screen.getByRole("combobox");
  await user.clear(input);
  await user.type(input, "Keep draft");
  server.use(
    http.get(`${base}/1/holdings`, () =>
      HttpResponse.json([
        ...rows,
        { ...current, ticker: "EXTRA", sector: "External Label" },
      ]),
    ),
  );
  rerender(<HoldingsTable portfolioId={1} refreshToken={1} />);
  expect(input).toHaveValue("Keep draft");
  await user.clear(input);
  expect(
    await screen.findByRole("option", { name: "External Label" }),
  ).toBeInTheDocument();
});

it("ignores an in-flight save after unmount", async () => {
  const gate = deferred();
  const started = vi.fn();
  const changed = vi.fn();
  server.use(
    http.patch(`${base}/1/holdings/AAPL`, async () => {
      started();
      await gate.promise;
      return HttpResponse.json({ ...current, sector: "Energy" });
    }),
  );
  const user = userEvent.setup();
  const { unmount } = render(
    <HoldingClassificationCell
      portfolioId={1}
      holding={current}
      field="sector"
      suggestions={["Energy"]}
      onChanged={changed}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Edit AAPL Sector" }));
  await user.clear(screen.getByRole("combobox"));
  await user.type(screen.getByRole("combobox"), "Energy");
  await user.click(screen.getByRole("button", { name: "Save AAPL Sector" }));
  await waitFor(() => expect(started).toHaveBeenCalled());
  expect(screen.getByRole("combobox")).toBeDisabled();
  unmount();
  await act(async () => {
    gate.release();
    await gate.promise;
  });
  expect(changed).not.toHaveBeenCalled();
});
