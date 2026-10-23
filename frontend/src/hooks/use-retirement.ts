"use client";

import * as React from "react";
import type { AsyncState } from "@/hooks/use-api-resource";
import { apiClient } from "@/lib/api-client";

/** Generation-tagged reads hide old data immediately, before effect cleanup runs. */
export function useRetirementResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
): AsyncState<T> {
  const [result, setResult] = React.useState<{ key: string; state: AsyncState<T> }>();
  React.useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted)
          setResult({ key, state: { status: "success", data } });
      },
      (error: unknown) => {
        if (!controller.signal.aborted)
          setResult({
            key,
            state: {
              status: "error",
              error: error instanceof Error ? error : new Error("Request failed"),
            },
          });
      },
    );
    return () => controller.abort();
    // The caller's explicit resource key captures every request dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return result?.key === key ? result.state : { status: "loading" };
}

export function useReportedAccount(id: number, version: number) {
  return useRetirementResource(`account:${id}:${version}`, async (signal) => {
    const [account, valuation, securities] = await Promise.all([
      apiClient.getPortfolio(id, signal),
      apiClient.getValuation(id, signal),
      apiClient.listSecurities(signal),
    ]);
    return { account, valuation, securities };
  });
}

/** One active write per mounted scope; cancellation also invalidates late results. */
export function useRetirementOperation(scope: string) {
  const current = React.useRef<AbortController | null>(null);
  React.useEffect(
    () => () => {
      current.current?.abort();
      current.current = null;
    },
    [scope],
  );
  return {
    start() {
      if (current.current) return null;
      const controller = new AbortController();
      current.current = controller;
      return controller;
    },
    active(controller: AbortController) {
      return current.current === controller && !controller.signal.aborted;
    },
    finish(controller: AbortController) {
      if (current.current === controller) current.current = null;
    },
    cancel() {
      current.current?.abort();
      current.current = null;
    },
  };
}
