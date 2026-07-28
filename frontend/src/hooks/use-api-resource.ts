"use client";

import * as React from "react";

/**
 * Discriminated-union state for an async fetch. Components switch on `status`
 * so loading, error, and success are handled exhaustively — TypeScript won't
 * let a caller read `data` before narrowing to `"success"`, which prevents the
 * classic "render undefined as 0" bug the honest-null design forbids.
 */
export type AsyncState<T> =
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "success"; data: T };

/**
 * Run an async fetcher on mount (and whenever `deps` change), tracking its
 * lifecycle. A per-run `ignore` flag discards a late response after the effect
 * re-runs or the component unmounts, so we never set state on a stale render —
 * the pattern React's own docs recommend. (We avoid `AbortController` here
 * because passing a DOM-created signal to Node's fetch trips an instance-of
 * check under jsdom; real cancellation belongs to the transport, not this hook.)
 */
export function useApiResource<T>(
  fetcher: (signal?: AbortSignal) => Promise<T>,
  deps: React.DependencyList,
): AsyncState<T> {
  const [state, setState] = React.useState<AsyncState<T>>({ status: "loading" });

  React.useEffect(() => {
    let ignore = false;
    // Intentional: reset to "loading" when deps change so a re-fetch shows the
    // spinner instead of stale data. This one-time sync with the network (an
    // external system) is exactly what the set-state-in-effect rule exempts.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState({ status: "loading" });

    fetcher()
      .then((data) => {
        if (!ignore) {
          setState({ status: "success", data });
        }
      })
      .catch((err: unknown) => {
        if (ignore) {
          return;
        }
        const error = err instanceof Error ? err : new Error("Unknown error");
        setState({ status: "error", error });
      });

    return () => {
      ignore = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
