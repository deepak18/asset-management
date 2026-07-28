"use client";

import * as React from "react";
import { worker } from "@/mocks/browser";

/**
 * Client-only mock bootstrap. Loaded exclusively via `next/dynamic` with
 * `ssr: false` (see providers.tsx), so the `msw/browser` import — which MSW maps
 * to `null` under the Node condition — is only ever resolved in the browser
 * bundle. It starts the worker, then renders children once interception is live
 * so the first data fetch can't race ahead of the mocks.
 */
export default function MockBootstrap({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    void worker.start({ onUnhandledRequest: "bypass" }).then(() => {
      if (active) {
        setReady(true);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  if (!ready) {
    return null;
  }
  return <>{children}</>;
}
