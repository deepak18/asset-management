"use client";

import * as React from "react";
import { apiClient } from "@/lib/api-client";
import type { ImportStatus, StatementImportStatus } from "@/types/domain";

/** Default gap between status polls — ~1s keeps the bar lively but gentle. */
export const IMPORT_POLL_INTERVAL_MS = 1000;

const TERMINAL: ReadonlySet<ImportStatus> = new Set<ImportStatus>(["SUCCEEDED", "FAILED"]);

/** Whether an import job has reached a state that stops polling. */
export function isTerminal(status: ImportStatus): boolean {
  return TERMINAL.has(status);
}

/**
 * Poll one import job to completion.
 *
 * Given the initial `202` job record from the upload, this refetches
 * `GET .../imports/{job_id}` every `intervalMs` until the status is terminal
 * (`SUCCEEDED`/`FAILED`), then stops. Polling also stops on unmount and when a
 * *new* job object is passed in — a self-scheduling `setTimeout` (not
 * `setInterval`) means at most one request is ever in flight, so there are no
 * leaked intervals or overlapping fetches. `onSucceeded` fires exactly once when
 * the job succeeds, so callers can refetch analytics.
 */
export function useImportJob(
  portfolioId: number,
  initial: StatementImportStatus | null,
  onSucceeded?: () => void,
  intervalMs: number = IMPORT_POLL_INTERVAL_MS,
): StatementImportStatus | null {
  const [status, setStatus] = React.useState<StatementImportStatus | null>(initial);

  // Keep the callback in a ref so changing its identity doesn't restart polling.
  const onSucceededRef = React.useRef(onSucceeded);
  React.useEffect(() => {
    onSucceededRef.current = onSucceeded;
  });

  React.useEffect(() => {
    // Sync displayed state to whichever job we're now tracking.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus(initial);

    if (initial == null) {
      return;
    }
    if (isTerminal(initial.status)) {
      if (initial.status === "SUCCEEDED") {
        onSucceededRef.current?.();
      }
      return;
    }

    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const next = await apiClient.getImport(portfolioId, initial.id);
        if (!active) {
          return;
        }
        setStatus(next);
        if (isTerminal(next.status)) {
          if (next.status === "SUCCEEDED") {
            onSucceededRef.current?.();
          }
          return; // terminal — stop scheduling.
        }
        timer = setTimeout(poll, intervalMs);
      } catch {
        // Transient poll failure: stop rather than hammer, keeping the last
        // known status on screen. The user can retry the upload.
      }
    };

    timer = setTimeout(poll, intervalMs);

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [portfolioId, initial, intervalMs]);

  return status;
}
