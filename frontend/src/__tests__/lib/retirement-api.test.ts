import { afterEach, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { apiClient } from "@/lib/api-client";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { demoRetirementCsv } from "@/mocks/retirement-fixtures";
import { retirementTransport } from "./retirement-transport";

const base = `${env.apiBaseUrl}/api/v1`;
const options = { as_of: "2026-10-20", currency: "USD", history_complete: false };
afterEach(() => vi.restoreAllMocks());

it("sends the same reviewed file/options and exact true without a JSON Content-Type; persists scoped reads", async () => {
  const transport = retirementTransport();
  const file = new File([demoRetirementCsv], "demo-retirement.csv", {
    type: "text/csv",
  });
  const preview = await apiClient.previewRetirementImport(99, file, options);
  expect(preview.reported_total).toBe("247.05");
  expect(preview.cost_basis).toBeNull();
  expect(preview.funds[0]?.ticker).toBeNull();
  const result = await apiClient.commitRetirementImport(
    99,
    file,
    options,
    preview.preview_token,
  );
  expect(result.status).toBe("COMMITTED");
  const writes = transport.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(writes).toHaveLength(2);
  for (const [, init] of writes) {
    expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
    const body = init?.body as FormData;
    expect(body.get("file")).toBe(file);
    expect(body.get("as_of")).toBe(options.as_of);
    expect(body.get("currency")).toBe("USD");
    expect(body.get("history_complete")).toBe("false");
  }
  const commit = writes[1]?.[1]?.body as FormData;
  expect(commit.get("confirmed")).toBe("true");
  expect(commit.get("preview_token")).toBe(preview.preview_token);
  expect(await apiClient.getValuation(99)).toMatchObject({
    status: "AVAILABLE",
    snapshot: { reported_total: "247.05" },
  });
  expect(await apiClient.listSecurities()).toMatchObject([{ id: 701, ticker: null }]);
  expect(await apiClient.listRetirementImports(99)).toHaveLength(1);
  expect(await apiClient.getRetirementImport(99, result.id)).toMatchObject({
    id: result.id,
    portfolio_id: 99,
  });
  expect(await apiClient.listAccountActivity(99)).toMatchObject([
    { fact: { amount: "24.70", dividend_amount: null } },
  ]);
  expect(await apiClient.getPortfolio(99)).toMatchObject({
    external_account_id: "000042",
    custodian: "Vanguard",
  });
  expect(await apiClient.listRetirementImports(1)).toEqual([]);
  await expect(apiClient.getRetirementImport(1, result.id)).rejects.toMatchObject({
    status: 404,
  });
  await expect(
    apiClient.previewRetirementImport(99, file, options),
  ).rejects.toMatchObject({
    status: 409,
    detail: expect.stringContaining("already imported"),
  });
});

it.each([404, 409, 413, 422])(
  "preserves retirement error status %s and backend detail",
  async (status) => {
    server.use(
      http.post(`${base}/portfolios/99/retirement-imports/preview`, () =>
        HttpResponse.json({ detail: "Actionable backend explanation" }, { status }),
      ),
    );
    await expect(
      apiClient.previewRetirementImport(
        99,
        new File(["fictional"], "sample.csv"),
        options,
      ),
    ).rejects.toMatchObject({ status, detail: "Actionable backend explanation" });
  },
);

it("preserves omitted metadata and explicitly clears nulls without losing leading zeros", async () => {
  await apiClient.updateAccount(99, {
    account_type: "ROTH_401K",
    external_account_id: "000042",
    custodian: "Vanguard",
  });
  expect(await apiClient.updateAccount(99, { custodian: null })).toMatchObject({
    account_type: "ROTH_401K",
    external_account_id: "000042",
    custodian: null,
  });
});

it("propagates an aborted read without publishing a successful result", async () => {
  const controller = new AbortController();
  controller.abort();
  await expect(apiClient.getValuation(99, controller.signal)).rejects.toMatchObject({
    name: "AbortError",
  });
});

it.each([404, 409, 413, 422])(
  "propagates commit errors with status %s",
  async (status) => {
    server.use(
      http.post(`${base}/portfolios/99/retirement-imports`, () =>
        HttpResponse.json({ detail: "Commit rejected by backend" }, { status }),
      ),
    );
    await expect(
      apiClient.commitRetirementImport(
        99,
        new File(["fictional"], "sample.csv"),
        options,
        "reviewed-token",
      ),
    ).rejects.toMatchObject({ status, detail: "Commit rejected by backend" });
  },
);
it("refuses arbitrary CSV in mock mode rather than pretending it parsed real data", async () => {
  retirementTransport();
  await expect(
    apiClient.previewRetirementImport(
      99,
      new File(["unrecognized fictional data"], "not-demo.csv"),
      options,
    ),
  ).rejects.toMatchObject({
    status: 422,
    detail: expect.stringContaining("Mock mode accepts only"),
  });
});
