import { setupWorker } from "msw/browser";
import { handlers } from "@/mocks/handlers";

/**
 * Browser-side MSW worker used during `npm run dev` when mock mode is enabled
 * (see providers.tsx). It requires the generated service worker file at
 * `public/mockServiceWorker.js` — run `npx msw init public/ --save` once after
 * install. This lets the whole dashboard render with zero live backend.
 */
export const worker = setupWorker(...handlers);
