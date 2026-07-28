import { http, HttpResponse } from "msw";
import { env } from "@/lib/env";
import {
  analyticsById,
  holdings,
  summariesById,
  transactions,
} from "@/mocks/fixtures";

/**
 * MSW request handlers implementing the OpenAPI contract against fixtures.
 *
 * These run in Node (Vitest) and in the browser (dev), so a component exercises
 * the real typed client while the network is fully faked. Unknown ids return a
 * 404 shaped like the backend's error, letting us test the "missing portfolio"
 * path honestly. Absolute URLs are built from the same base the client uses.
 */
const base = env.apiBaseUrl;

function notFound(detail: string): HttpResponse {
  return HttpResponse.json({ detail }, { status: 404 });
}

export const handlers = [
  http.get(`${base}/health`, () => HttpResponse.json({ status: "ok" })),

  http.get(`${base}/api/v1/portfolios/:id`, ({ params }) => {
    const id = Number(params.id);
    const summary = summariesById[id];
    return summary ? HttpResponse.json(summary) : notFound("Portfolio not found");
  }),

  http.get(`${base}/api/v1/portfolios/:id/transactions`, ({ params }) => {
    const id = Number(params.id);
    if (!summariesById[id]) {
      return notFound("Portfolio not found");
    }
    // Only portfolio 1 carries a populated ledger; others are empty.
    return HttpResponse.json(id === 1 ? transactions : []);
  }),

  http.get(`${base}/api/v1/portfolios/:id/holdings`, ({ params }) => {
    const id = Number(params.id);
    if (!summariesById[id]) {
      return notFound("Portfolio not found");
    }
    return HttpResponse.json(id === 1 ? holdings : []);
  }),

  http.get(`${base}/api/v1/portfolios/:id/analytics`, ({ params }) => {
    const id = Number(params.id);
    const analytics = analyticsById[id];
    return analytics ? HttpResponse.json(analytics) : notFound("Analytics not found");
  }),
];
