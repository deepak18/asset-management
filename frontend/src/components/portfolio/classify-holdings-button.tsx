"use client";

import * as React from "react";
import { apiClient, ApiError } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import type { ClassificationFailure, HoldingInfo } from "@/types/domain";

interface RunSummary {
  classified: HoldingInfo[];
  unresolved: string[];
  remaining: number;
  passes: number;
  failures: ClassificationFailure[];
}

type Phase = "idle" | "running" | "done" | "unavailable" | "error";

/**
 * "Classify holdings" — backfill sector/industry from company profiles.
 *
 * A broker statement carries no classification, so imported holdings group under
 * `UNCLASSIFIED`. This drains that bucket, looping while `remaining` is non-zero
 * because each call is deliberately capped.
 *
 * A `503` is handled differently from every other failure on purpose: it means
 * no market-data provider is configured, so retrying is pointless — the remedy
 * is an API key (or classifying by hand). We therefore withdraw the button
 * instead of inviting the user to click it again.
 */
export function ClassifyHoldingsButton(props: {
  portfolioId: number;
  onChanged?: () => void;
}) {
  return <ClassificationRun key={props.portfolioId} {...props} />;
}

function ClassificationRun({
  portfolioId,
  onChanged,
}: {
  portfolioId: number;
  onChanged?: () => void;
}) {
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [summary, setSummary] = React.useState<RunSummary | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);

  // Abort in flight work on unmount so a long backfill cannot set state on a
  // dead component (or keep hitting the API after the user navigates away).
  const abortRef = React.useRef<AbortController | null>(null);
  React.useEffect(() => {
    return () => abortRef.current?.abort();
  }, [portfolioId]);

  async function run() {
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;

    setPhase("running");
    setSummary(null);
    setMessage(null);

    const classified: HoldingInfo[] = [];
    const unresolved: string[] = [];
    let remaining = 0;
    let passes = 0;
    let afterTicker: string | undefined;
    const cursors = new Set<string>();
    const failures: ClassificationFailure[] = [];
    let previousRemaining: number | undefined;

    try {
      for (;;) {
        const result = await apiClient.classifyHoldings(
          portfolioId,
          { afterTicker },
          controller.signal,
        );
        if (controller.signal.aborted) return;
        classified.push(...result.classified);
        unresolved.push(...result.unresolved);
        failures.push(...result.failures);
        remaining = result.remaining;
        passes += 1;

        // Live progress: each pass is a real round-trip, so show what landed.
        setSummary({
          classified: [...classified],
          unresolved: [...unresolved],
          remaining,
          passes,
          failures: [...failures],
        });

        if (remaining <= 0) break;
        if (
          !result.next_cursor ||
          cursors.has(result.next_cursor) ||
          (afterTicker != null && result.next_cursor <= afterTicker) ||
          (previousRemaining != null && remaining >= previousRemaining)
        ) {
          throw new Error(
            "Classification stopped: the API did not supply an advancing cursor.",
          );
        }
        cursors.add(result.next_cursor);
        afterTicker = result.next_cursor;
        previousRemaining = remaining;
      }
      setPhase("done");
      if (classified.length > 0) {
        onChanged?.();
      }
    } catch (err) {
      if (controller.signal.aborted) {
        return;
      }
      if (err instanceof ApiError && err.status === 503) {
        setPhase("unavailable");
        setMessage(
          err.detail ??
            "No market-data provider is configured, so holdings cannot be classified automatically.",
        );
      } else {
        setPhase("error");
        setMessage(err instanceof Error ? err.message : "Could not classify holdings.");
      }
      // Partial progress still counts — refresh whatever did land.
      if (classified.length > 0) {
        onChanged?.();
      }
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      {phase === "unavailable" ? null : (
        <Button
          type="button"
          variant="outline"
          onClick={() => void run()}
          disabled={phase === "running"}
        >
          {phase === "running" ? "Classifying…" : "Classify Holdings"}
        </Button>
      )}

      {phase === "unavailable" ? (
        <p role="alert" className="max-w-prose text-sm text-destructive">
          {message} Add a market-data API key to enable automatic classification, or set
          sector and industry by hand below.
        </p>
      ) : null}

      {phase === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      ) : null}

      {summary ? (
        <div role="status" className="max-w-prose space-y-1 text-sm">
          <p
            className={
              summary.classified.length > 0 ? "text-positive" : "text-muted-foreground"
            }
          >
            Classified {summary.classified.length} holding
            {summary.classified.length === 1 ? "" : "s"}
            {summary.classified.length > 0
              ? `: ${summary.classified.map((h) => h.ticker).join(", ")}`
              : ""}
            .
          </p>
          {summary.unresolved.length > 0 ? (
            <p className="text-muted-foreground">
              Unresolved: {summary.unresolved.join(", ")}. Edit these holdings manually
              or try a fresh sweep later.
            </p>
          ) : null}
          {phase === "running" ? (
            <p>{summary.remaining} holdings remaining in this sweep.</p>
          ) : null}
          {phase === "done" ? (
            <p>Sweep complete. {summary.remaining} remaining.</p>
          ) : null}
          <ul>
            {summary.failures.map((failure) => (
              <li key={failure.ticker}>
                {failure.ticker}:{" "}
                {failure.reason === "PROVIDER_UNAVAILABLE"
                  ? "Provider unavailable (quota or outage). Try a fresh sweep later; manual editing still works."
                  : "No usable profile returned. Enter sector and industry manually, or try again later."}
              </li>
            ))}
          </ul>
          {phase === "done" && summary.remaining > 0 ? (
            <p className="text-muted-foreground">
              {summary.remaining} holding{summary.remaining === 1 ? "" : "s"} still
              unclassified — run it again.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
