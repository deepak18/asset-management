import { http, HttpResponse } from "msw";
import { env } from "@/lib/env";
import type {
  HoldingClassificationUpdate,
  PortfolioCreate,
  PositionSnapshot,
  TransactionInput,
} from "@/types/domain";
import {
  classifyHoldings,
  createImport,
  createPortfolio,
  deleteTransaction,
  findPortfolio,
  getAnalytics,
  getHoldings,
  getHoldingAnalytics,
  getImport,
  getTransactions,
  ingest,
  listImports,
  listPortfolios,
  updateHoldingClassification,
  getHistoryReview,
  confirmHistoryReview,
  addMockTransactions,
} from "@/mocks/state";
import { retirementHandlers } from "@/mocks/retirement-handlers";

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
  ...retirementHandlers,
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

  http.post(
    `${base}/api/v1/portfolios/:id/transactions`,
    async ({ params, request }) => {
      const id = Number(params.id);
      if (!findPortfolio(id)) {
        return notFound("Portfolio not found");
      }
      const body = (await request.json()) as TransactionInput[];
      if (
        body.some((row) =>
          Object.keys(row).some(
            (key) =>
              ![
                "ticker",
                "type",
                "trade_date",
                "currency",
                "quantity",
                "price",
                "fees",
                "amount",
                "split_ratio",
                "sector",
                "industry",
              ].includes(key),
          ),
        )
      ) {
        return HttpResponse.json(
          { detail: "Unknown transaction input field" },
          { status: 422 },
        );
      }
      return HttpResponse.json(addMockTransactions(id, body), {
        status: 201,
      });
    },
  ),

  http.get(`${base}/api/v1/portfolios/:id/holdings`, ({ params }) => {
    const holds = getHoldings(Number(params.id));
    return holds ? HttpResponse.json(holds) : notFound("Portfolio not found");
  }),

  http.post(
    `${base}/api/v1/portfolios/:id/holdings/classify`,
    ({ params, request }) => {
      const url = new URL(request.url);
      const refresh = url.searchParams.get("refresh") === "true";
      const rawLimit = url.searchParams.get("limit");
      const limit = rawLimit == null ? 25 : Number(rawLimit);
      if (!Number.isInteger(limit) || limit < 1 || limit > 200) {
        return HttpResponse.json(
          { detail: [{ msg: "limit must be between 1 and 200" }] },
          { status: 422 },
        );
      }
      const attempt = classifyHoldings(
        Number(params.id),
        refresh,
        limit,
        url.searchParams.get("after_ticker") ?? undefined,
      );
      return attempt.ok
        ? HttpResponse.json(attempt.result)
        : HttpResponse.json({ detail: attempt.detail }, { status: attempt.status });
    },
  ),

  http.patch(
    `${base}/api/v1/portfolios/:id/holdings/:ticker`,
    async ({ params, request }) => {
      const body = (await request.json()) as HoldingClassificationUpdate;
      if (
        !Object.keys(body).length ||
        Object.keys(body).some((key) => key !== "sector" && key !== "industry") ||
        [body.sector, body.industry].some(
          (value) =>
            value != null &&
            (typeof value !== "string" || !value.trim() || value.length > 80),
        )
      ) {
        return HttpResponse.json(
          { detail: [{ msg: "Provide a sector and/or an industry." }] },
          { status: 422 },
        );
      }
      const updated = updateHoldingClassification(
        Number(params.id),
        String(params.ticker),
        body,
      );
      return updated ? HttpResponse.json(updated) : notFound("Holding not found");
    },
  ),

  http.get(`${base}/api/v1/portfolios/:id/holdings/:ticker/analytics`, ({ params }) => {
    const analytics = getHoldingAnalytics(Number(params.id), String(params.ticker));
    return analytics
      ? HttpResponse.json(analytics)
      : notFound("Portfolio or holding not found");
  }),

  http.get(`${base}/api/v1/portfolios/:id/holdings/:ticker`, ({ params }) => {
    const holding = getHoldings(Number(params.id))?.find(
      (row) => row.ticker === String(params.ticker).toUpperCase(),
    );
    return holding ? HttpResponse.json(holding) : notFound("Holding not found");
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
    return HttpResponse.json(ingest(id, uniqueTickers(body), body.length), {
      status: 201,
    });
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

  http.delete(
    `${base}/api/v1/portfolios/:id/transactions/:transactionId`,
    ({ params }) => {
      const result = deleteTransaction(Number(params.id), Number(params.transactionId));
      return result.ok
        ? new HttpResponse(null, { status: 204 })
        : HttpResponse.json({ detail: result.detail }, { status: result.status });
    },
  ),

  http.get(`${base}/api/v1/portfolios/:id/holdings/:ticker/history`, ({ params }) => {
    const review = getHistoryReview(Number(params.id), String(params.ticker));
    return review
      ? HttpResponse.json(review)
      : notFound("Portfolio or holding not found");
  }),
  http.post(
    `${base}/api/v1/portfolios/:id/holdings/:ticker/history`,
    async ({ params, request }) => {
      const body: unknown = await request.json();
      if (
        !body ||
        typeof body !== "object" ||
        !("confirmed" in body) ||
        body.confirmed !== true ||
        !("review_token" in body) ||
        typeof body.review_token !== "string" ||
        Object.keys(body).some((key) => !["confirmed", "review_token"].includes(key))
      ) {
        return HttpResponse.json(
          { detail: "Provide review_token and boolean true acknowledgement" },
          { status: 422 },
        );
      }
      const id = Number(params.id);
      const ticker = String(params.ticker);
      if (!getHistoryReview(id, ticker))
        return notFound("Portfolio or holding not found");
      const result = confirmHistoryReview(id, ticker, body.review_token);
      return result
        ? HttpResponse.json(result)
        : HttpResponse.json(
            { detail: "History changed or blocking gaps remain" },
            { status: 409 },
          );
    },
  ),
];
