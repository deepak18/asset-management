/**
 * Single, validated entry point for public runtime config.
 *
 * Next inlines `NEXT_PUBLIC_*` vars at build time, so we read them once here and
 * fail fast with a clear message if the API base URL is missing/blank rather
 * than letting an `undefined` silently produce requests to the wrong origin.
 * A localhost default keeps `npm run dev` working with zero setup.
 */
const DEFAULT_API_BASE_URL = "http://localhost:8000";

function resolveApiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  const value = raw && raw.length > 0 ? raw : DEFAULT_API_BASE_URL;
  // Strip a trailing slash so path joining (`${base}/api/v1/...`) never doubles up.
  return value.replace(/\/+$/, "");
}

export const env = {
  apiBaseUrl: resolveApiBaseUrl(),
  /** When "enabled", the browser boots the MSW worker so the UI runs mock-only. */
  apiMocking: process.env.NEXT_PUBLIC_API_MOCKING?.trim() === "enabled",
} as const;
