"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { env } from "@/lib/env";

/**
 * Client bootstrap. When mock mode is enabled (NEXT_PUBLIC_API_MOCKING=enabled),
 * the whole dashboard runs against MSW fixtures with zero live backend; in live
 * mode this is a transparent pass-through.
 *
 * The MSW bootstrap is pulled in with `ssr: false` so it — and its `msw/browser`
 * dependency — never enter the server bundle (MSW disables that subpath under
 * Node), keeping the production build clean.
 */
const MockBootstrap = dynamic(() => import("@/mocks/mock-bootstrap"), {
  ssr: false,
});

export function Providers({ children }: { children: React.ReactNode }) {
  if (env.apiMocking) {
    return <MockBootstrap>{children}</MockBootstrap>;
  }
  return <>{children}</>;
}
