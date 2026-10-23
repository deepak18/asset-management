import { http, HttpResponse } from "msw";
import { env } from "@/lib/env";
import {
  findPortfolio,
  listPortfolios,
  mockRetirement,
  updateMockAccount,
} from "@/mocks/state";
import {
  demoActivity,
  demoPreview,
  demoRetirementCsv,
  demoSecurity,
  demoValuation,
} from "@/mocks/retirement-fixtures";
import type {
  AccountUpdate,
  RetirementOptions,
  RetirementImport,
} from "@/types/domain";

const base = `${env.apiBaseUrl}/api/v1`;
const error = (detail: string, status: number) =>
  HttpResponse.json({ detail }, { status });
const token = (id: number, options: RetirementOptions) =>
  JSON.stringify([id, options, findPortfolio(id), mockRetirement(id).imports.length]);

async function reviewRequest(request: Request, id: number) {
  if (!findPortfolio(id)) return error("Portfolio not found", 404);
  const form = await request.formData();
  const file = form.get("file");
  if (
    !file ||
    typeof file === "string" ||
    file.name !== "demo-retirement.csv" ||
    (await file.text()) !== demoRetirementCsv
  )
    return error(
      "Mock mode accepts only the fictitious demo-retirement.csv bytes; use the live backend for your CSV.",
      422,
    );
  const asOf = form.get("as_of");
  if (
    typeof asOf !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(asOf) ||
    form.get("currency") !== "USD"
  )
    return error("Explicit holdings date and USD are required", 422);
  if (mockRetirement(id).imports.length)
    return error(
      "This exact file was already imported. Inspect persisted history instead.",
      409,
    );
  const account = findPortfolio(id)!;
  if (account.base_currency !== "USD")
    return error("Mock retirement imports require a USD account", 422);
  if (
    account.external_account_id &&
    account.external_account_id.replace(/^0+/, "") !== "42"
  )
    return error("Source account does not match the selected account", 409);
  const options: RetirementOptions = {
    as_of: asOf,
    currency: "USD",
    history_complete: form.get("history_complete") === "true",
  };
  return { form, preview: demoPreview(id, options, token(id, options)) };
}

export const retirementHandlers = [
  http.patch(`${base}/portfolios/:id/account`, async ({ params, request }) => {
    const body = (await request.json()) as AccountUpdate;
    const result = updateMockAccount(Number(params.id), body);
    return result ? HttpResponse.json(result) : error("Portfolio not found", 404);
  }),
  http.get(`${base}/securities`, () =>
    HttpResponse.json(
      listPortfolios().some((item) => mockRetirement(item.id).imports.length)
        ? [demoSecurity]
        : [],
    ),
  ),
  http.get(`${base}/portfolios/:id/valuations`, ({ params }) =>
    findPortfolio(Number(params.id))
      ? HttpResponse.json(mockRetirement(Number(params.id)).valuation)
      : error("Portfolio not found", 404),
  ),
  http.post(
    `${base}/portfolios/:id/retirement-imports/preview`,
    async ({ params, request }) => {
      const result = await reviewRequest(request, Number(params.id));
      return result instanceof Response ? result : HttpResponse.json(result.preview);
    },
  ),
  http.post(
    `${base}/portfolios/:id/retirement-imports`,
    async ({ params, request }) => {
      const id = Number(params.id);
      const result = await reviewRequest(request, id);
      if (result instanceof Response) return result;
      if (result.form.get("confirmed") !== "true")
        return error("Confirmation must be exactly true", 422);
      if (result.form.get("preview_token") !== result.preview.preview_token)
        return error("Review is stale; preview again", 409);
      if (!result.preview.can_commit)
        return error("Inception history does not reconcile", 422);
      const record: RetirementImport = {
        id: 901,
        portfolio_id: id,
        valuation_id: 801,
        imported_at: "2026-10-22T12:00:00Z",
        storage_key: "mock/fictional-checksum",
        status: "COMMITTED",
        preview: result.preview,
      };
      const state = mockRetirement(id);
      state.imports = [record];
      state.activity = [
        {
          id: 1001,
          import_id: 901,
          portfolio_id: id,
          security_id: 701,
          currency: "USD",
          source_code: "VANGUARD",
          fact: demoActivity,
        },
      ];
      state.valuation = demoValuation(id, result.preview.options.as_of);
      const account = findPortfolio(id)!;
      updateMockAccount(id, {
        external_account_id: account.external_account_id ?? "000042",
        custodian: account.custodian ?? "Vanguard",
      });
      return HttpResponse.json(record, { status: 201 });
    },
  ),
  http.get(`${base}/portfolios/:id/retirement-imports`, ({ params }) =>
    findPortfolio(Number(params.id))
      ? HttpResponse.json(mockRetirement(Number(params.id)).imports)
      : error("Portfolio not found", 404),
  ),
  http.get(`${base}/portfolios/:id/retirement-imports/:importId`, ({ params }) => {
    const record = mockRetirement(Number(params.id)).imports.find(
      (item) => item.id === Number(params.importId),
    );
    return record
      ? HttpResponse.json(record)
      : error("Import not found in this portfolio", 404);
  }),
  http.get(`${base}/portfolios/:id/account-activity`, ({ params }) =>
    findPortfolio(Number(params.id))
      ? HttpResponse.json(mockRetirement(Number(params.id)).activity)
      : error("Portfolio not found", 404),
  ),
];
