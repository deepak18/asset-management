import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { createImport } from "@/mocks/state";
import { ImportPanel } from "@/components/portfolio/import-panel";

/**
 * Upload a CSV through the (visually hidden but accessible) file input.
 *
 * jsdom does not serialize `FormData` bodies, so the default handler can't read
 * the uploaded filename here — the success path relies on the benign default
 * (a job that polls to SUCCEEDED), and the error paths are driven by per-test
 * handler overrides. In a real browser the default handler reads the file.
 */
async function uploadFile(user: ReturnType<typeof userEvent.setup>, filename: string) {
  const file = new File(["Activity Date,Instrument"], filename, { type: "text/csv" });
  await user.upload(screen.getByLabelText("Upload broker statement"), file);
}

describe("ImportPanel", () => {
  it("uploads, shows progress, then reports success with warnings and refetches", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    render(<ImportPanel portfolioId={1} onSuccess={onSuccess} pollIntervalMs={5} />);

    await uploadFile(user, "history.csv");

    // Polls advance the mock job to a terminal SUCCEEDED state.
    await waitFor(() => expect(screen.getByText("SUCCEEDED")).toBeInTheDocument());
    expect(screen.getByText(/Imported 3 transactions/)).toBeInTheDocument();
    expect(screen.getByText(/need manual entry/)).toBeInTheDocument();
    expect(screen.getByText(/options trade/)).toBeInTheDocument();
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("offers 'import anyway' on a 409 duplicate, then succeeds with the override", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${env.apiBaseUrl}/api/v1/portfolios/1/imports`, ({ request }) => {
        const allow = new URL(request.url).searchParams.get("allow_duplicate") === "true";
        if (!allow) {
          return HttpResponse.json(
            { detail: "This exact file was already imported." },
            { status: 409 },
          );
        }
        const result = createImport(1, "history.csv", 100, true);
        return HttpResponse.json(result.ok ? result.job : {}, { status: 202 });
      }),
    );
    render(<ImportPanel portfolioId={1} pollIntervalMs={5} />);

    await uploadFile(user, "duplicate.csv");

    // The duplicate guard is surfaced with an explicit override affordance.
    expect(await screen.findByText(/already imported/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Import anyway" }));

    await waitFor(() => expect(screen.getByText("SUCCEEDED")).toBeInTheDocument());
  });

  it("explains a 413 (too large) upload without offering a retry", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${env.apiBaseUrl}/api/v1/portfolios/1/imports`, () =>
        HttpResponse.json({ detail: "That file is over the 5 MB limit." }, { status: 413 }),
      ),
    );
    render(<ImportPanel portfolioId={1} pollIntervalMs={5} />);

    await uploadFile(user, "large-export.csv");

    expect(await screen.findByRole("alert")).toHaveTextContent("over the 5 MB limit");
    expect(screen.queryByRole("button", { name: "Import anyway" })).not.toBeInTheDocument();
  });
});
