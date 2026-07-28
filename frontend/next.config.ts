import type { NextConfig } from "next";

/**
 * Next.js configuration.
 *
 * `reactStrictMode` double-invokes effects in development to surface unsafe
 * side effects early — cheap insurance for a data-fetching-heavy dashboard.
 * We keep this file intentionally minimal; the browser talks to the backend
 * only through the versioned REST API, so there are no rewrites/proxies that
 * would blur the frontend/API separation.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
