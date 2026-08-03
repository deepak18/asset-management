"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { env } from "@/lib/env";
import { PortfolioSelectionProvider } from "@/hooks/use-portfolio-selection";

/**
 * Client bootstrap. When mock mode is enabled (NEXT_PUBLIC_API_MOCKING=enabled),
 * the whole dashboard runs against MSW fixtures with zero live backend; in live
 * mode this is a transparent pass-through.
 *
 * The MSW bootstrap is pulled in with `ssr: false` so it — and its `msw/browser`
 * dependency — never enter the server bundle (MSW disables that subpath under
 * Node), keeping the production build clean. The portfolio-selection context
 * wraps the app *inside* the mock boot so its first `listPortfolios` fetch is
 * intercepted, and so the app-shell picker and the dashboard share one selection.
 */
const MockBootstrap = dynamic(() => import("@/mocks/mock-bootstrap"), {
  ssr: false,
});

export function Providers({ children }: { children: React.ReactNode }) {
  const app = <PortfolioSelectionProvider>{children}</PortfolioSelectionProvider>;
  if (env.apiMocking) {
    return <MockBootstrap>{app}</MockBootstrap>;
  }
  return app;
}
