import { http, HttpResponse } from "msw";
import { env } from "@/lib/env";
import type {
  PortfolioCreate,
  PositionSnapshot,
  TransactionInput,
} from "@/types/domain";
import {
  createImport,
  createPortfolio,
  findPortfolio,
  getAnalytics,
  getHoldings,
  getImport,
  getTransactions,
  ingest,
  listImports,
  listPortfolios,
} from "@/mocks/state";

/**
 * MSW request handlers implementing the OpenAPI contract against fixtures +
 * mutable mock state (see `mocks/state.ts`).
 *
 * These run in Node (Vitest) and in the browser (dev), so a component exercises
 * the real typed client while the network is fully faked. Reads degrade to a 404
 * shaped like the backend's error for unknown ids; writes record their effect in
 * state so the UI can observe it (new portfolio in the picker, an import job that
 * progresses across polls). Absolute URLs are built from the client's base URL.
 */
const base = env.apiBaseUrl;

function notFound(detail: string): HttpResponse {
  return HttpResponse.json({ detail }, { status: 404 });
}

/** Unique, order-preserving ticker list from a batch of write inputs. */
function uniqueTickers(items: { ticker?: string }[]): string[] {
  const seen = new Set<string>();
  for (const item of items) {
    if (item.ticker) {
      seen.add(item.ticker.toUpperCase());
    }
  }
  return [...seen];
}

export const handlers = [
  http.get(`${base}/health`, () => HttpResponse.json({ status: "ok" })),

  http.get(`${base}/api/v1/portfolios`, () => HttpResponse.json(listPortfolios())),

  http.post(`${base}/api/v1/portfolios`, async ({ request }) => {
    const body = (await request.json()) as PortfolioCreate;
    return HttpResponse.json(createPortfolio(body), { status: 201 });
  }),

  http.get(`${base}/api/v1/portfolios/:id`, ({ params }) => {
    const summary = findPortfolio(Number(params.id));
    return summary ? HttpResponse.json(summary) : notFound("Portfolio not found");
  }),

  http.get(`${base}/api/v1/portfolios/:id/transactions`, ({ params }) => {
    const txns = getTransactions(Number(params.id));
    return txns ? HttpResponse.json(txns) : notFound("Portfolio not found");
  }),

  http.post(`${base}/api/v1/portfolios/:id/transactions`, async ({ params, request }) => {
    const id = Number(params.id);
    if (!findPortfolio(id)) {
      return notFound("Portfolio not found");
    }
    const body = (await request.json()) as TransactionInput[];
    return HttpResponse.json(ingest(id, uniqueTickers(body), body.length), { status: 201 });
  }),

  http.get(`${base}/api/v1/portfolios/:id/holdings`, ({ params }) => {
    const holds = getHoldings(Number(params.id));
    return holds ? HttpResponse.json(holds) : notFound("Portfolio not found");
  }),

  http.get(`${base}/api/v1/portfolios/:id/analytics`, ({ params }) => {
    const analytics = getAnalytics(Number(params.id));
    return analytics ? HttpResponse.json(analytics) : notFound("Analytics not found");
  }),

  http.post(`${base}/api/v1/portfolios/:id/positions`, async ({ params, request }) => {
    const id = Number(params.id);
    if (!findPortfolio(id)) {
      return notFound("Portfolio not found");
    }
    const body = (await request.json()) as PositionSnapshot[];
    return HttpResponse.json(ingest(id, uniqueTickers(body), body.length), { status: 201 });
  }),

  http.post(`${base}/api/v1/portfolios/:id/imports`, async ({ params, request }) => {
    const id = Number(params.id);
    if (!findPortfolio(id)) {
      return notFound("Portfolio not found");
    }
    const url = new URL(request.url);
    const allowDuplicate = url.searchParams.get("allow_duplicate") === "true";
    // Read the uploaded filename/size to drive the demo error paths. This works
    // in the browser (dev mock mode); under jsdom (Vitest) `FormData` bodies do
    // not serialize, so parsing is best-effort and tests override this handler
    // to exercise the 409/413/422 branches deterministically.
    let filename = "upload.csv";
    let size = 0;
    try {
      const form = await request.formData();
      const file = form.get("file");
      if (file instanceof File) {
        filename = file.name;
        size = file.size;
      }
    } catch {
      // Unparseable body (e.g. jsdom) — fall back to the benign defaults above.
    }
    const result = createImport(id, filename, size, allowDuplicate);
    if (!result.ok) {
      return HttpResponse.json({ detail: result.detail }, { status: result.status });
    }
    return HttpResponse.json(result.job, { status: 202 });
  }),

  http.get(`${base}/api/v1/portfolios/:id/imports`, ({ params }) => {
    const id = Number(params.id);
    if (!findPortfolio(id)) {
      return notFound("Portfolio not found");
    }
    return HttpResponse.json(listImports(id));
  }),

  http.get(`${base}/api/v1/portfolios/:id/imports/:jobId`, ({ params }) => {
    const job = getImport(Number(params.id), Number(params.jobId));
    return job ? HttpResponse.json(job) : notFound("Import job not found");
  }),
];
