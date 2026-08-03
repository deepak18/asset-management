"use client";

import * as React from "react";
import { UploadCloud } from "lucide-react";
import { apiClient, ApiError } from "@/lib/api-client";
import { useApiResource } from "@/hooks/use-api-resource";
import { useImportJob, isTerminal, IMPORT_POLL_INTERVAL_MS } from "@/hooks/use-import-job";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { EmptyState, ErrorState } from "@/components/shared/states";
import type { ImportStatus, StatementImportStatus } from "@/types/domain";

interface UploadError {
  status: number;
  message: string;
  /** Set when the failed file can be retried with `allow_duplicate=true`. */
  duplicate: boolean;
}

/** Map a size-cap / parse / duplicate failure to a friendly explanation. */
function explainUploadError(err: ApiError): UploadError {
  const message =
    err.detail ??
    (err.status === 409
      ? "This file was already imported."
      : err.status === 413
        ? "That file is over the 5 MB limit."
        : err.status === 422
          ? "That file isn't a readable Robinhood activity CSV."
          : err.message);
  return { status: err.status, message, duplicate: err.status === 409 };
}

function statusVariant(status: ImportStatus): "positive" | "negative" | "muted" | "default" {
  switch (status) {
    case "SUCCEEDED":
      return "positive";
    case "FAILED":
      return "negative";
    case "PENDING":
    case "RUNNING":
      return "muted";
  }
}

/** The live progress + outcome view for the job currently being tracked. */
function JobStatus({ job, currency }: { job: StatementImportStatus; currency?: string }) {
  void currency;
  const done = isTerminal(job.status);
  const total = job.total_rows;
  return (
    <div className="space-y-3 rounded-md border p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{job.original_filename}</span>
        <Badge variant={statusVariant(job.status)}>{job.status}</Badge>
      </div>

      {!done ? (
        <div className="space-y-1">
          <Progress
            label="Import progress"
            value={total == null ? null : job.processed_rows}
            max={total ?? 100}
          />
          <p className="text-xs text-muted-foreground tabular-nums">
            {total == null
              ? `${job.processed_rows} rows processed — counting file…`
              : `${job.processed_rows} / ${total} rows`}
          </p>
        </div>
      ) : null}

      {job.status === "SUCCEEDED" ? (
        <div className="space-y-2 text-sm">
          <p className="text-positive" role="status">
            Imported {job.created_transactions} transaction
            {job.created_transactions === 1 ? "" : "s"}
            {job.tickers.length > 0 ? ` across ${job.tickers.length} ticker(s).` : "."}
          </p>
          {job.tickers.length > 0 ? (
            <p className="text-muted-foreground">Tickers: {job.tickers.join(", ")}</p>
          ) : null}
          {job.warnings.length > 0 ? (
            <div>
              <p className="font-medium">
                {job.warnings.length} row(s) need manual entry:
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
                {job.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {job.status === "FAILED" ? (
        <ErrorState message={job.error ?? "The import failed."} />
      ) : null}
    </div>
  );
}

/** Compact newest-first history of prior imports for this portfolio. */
function ImportHistory({
  portfolioId,
  version,
}: {
  portfolioId: number;
  version: number;
}) {
  const state = useApiResource(() => apiClient.listImports(portfolioId), [portfolioId, version]);
  if (state.status !== "success" || state.data.length === 0) {
    return null;
  }
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground">Import history</p>
      <ul className="space-y-1 text-sm">
        {state.data.map((job) => (
          <li key={job.id} className="flex items-center justify-between gap-2">
            <span className="truncate">{job.original_filename}</span>
            <Badge variant={statusVariant(job.status)}>{job.status}</Badge>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * CSV import panel — the async workhorse (§5).
 *
 * Drag-drop or pick a Robinhood activity CSV → `POST .../imports` (expects
 * `202`) → poll the job to a terminal state via {@link useImportJob} (no leaked
 * intervals). Progress is indeterminate until the backend counts `total_rows`.
 * On success we show created transactions, tickers, and every warning (the rows
 * — options/transfers/splits — that still need manual entry) and refetch the
 * dashboard; on failure we show the error. A 409 (already imported) offers an
 * explicit "import anyway" that retries with `allow_duplicate=true`; 413/422 are
 * explained.
 */
export function ImportPanel({
  portfolioId,
  currency,
  onSuccess,
  pollIntervalMs = IMPORT_POLL_INTERVAL_MS,
}: {
  portfolioId: number;
  currency?: string;
  onSuccess?: () => void;
  /** Poll cadence; overridable so tests don't wait real seconds. */
  pollIntervalMs?: number;
}) {
  const [job, setJob] = React.useState<StatementImportStatus | null>(null);
  const [uploading, setUploading] = React.useState(false);
  const [uploadError, setUploadError] = React.useState<UploadError | null>(null);
  const [pendingFile, setPendingFile] = React.useState<File | null>(null);
  const [dragOver, setDragOver] = React.useState(false);
  const [historyVersion, setHistoryVersion] = React.useState(0);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleSucceeded = React.useCallback(() => {
    onSuccess?.();
  }, [onSuccess]);

  const live = useImportJob(portfolioId, job, handleSucceeded, pollIntervalMs);

  // Refresh the history list whenever a tracked job reaches a terminal state.
  const liveStatus = live?.status;
  React.useEffect(() => {
    if (liveStatus && isTerminal(liveStatus)) {
      // Bumping a token to re-run the history fetch — a deliberate sync with the
      // external import job, exactly what this rule exempts.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHistoryVersion((v) => v + 1);
    }
  }, [liveStatus]);

  const submit = React.useCallback(
    async (file: File, allowDuplicate: boolean) => {
      setUploading(true);
      setUploadError(null);
      try {
        const initial = await apiClient.createImport(
          portfolioId,
          file,
          { sourceFormat: "robinhood_csv", allowDuplicate },
        );
        setJob(initial);
        setPendingFile(null);
      } catch (err) {
        if (err instanceof ApiError) {
          const parsed = explainUploadError(err);
          setUploadError(parsed);
          setPendingFile(parsed.duplicate ? file : null);
        } else {
          setUploadError({ status: 0, message: "Upload failed.", duplicate: false });
        }
      } finally {
        setUploading(false);
      }
    },
    [portfolioId],
  );

  function onFilePicked(files: FileList | null) {
    const file = files?.[0];
    if (file) {
      void submit(file, false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Import broker statement</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            onFilePicked(e.dataTransfer.files);
          }}
          className={`flex flex-col items-center justify-center gap-2 rounded-md border border-dashed p-6 text-center ${
            dragOver ? "border-primary bg-accent" : "border-input"
          }`}
        >
          <UploadCloud className="h-6 w-6 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            Drag a Robinhood activity CSV here, or
          </p>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            aria-label="Upload broker statement"
            onChange={(e) => onFilePicked(e.target.files)}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={uploading}
            onClick={() => inputRef.current?.click()}
          >
            {uploading ? "Uploading…" : "Choose file"}
          </Button>
          <p className="text-xs text-muted-foreground">CSV up to 5 MB.</p>
        </div>

        {uploadError ? (
          <div className="space-y-2">
            <ErrorState message={uploadError.message} />
            {uploadError.duplicate && pendingFile ? (
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={uploading}
                onClick={() => void submit(pendingFile, true)}
              >
                Import anyway
              </Button>
            ) : null}
          </div>
        ) : null}

        {live ? <JobStatus job={live} currency={currency} /> : null}

        {!live && !uploadError ? (
          <EmptyState message="No import in progress." />
        ) : null}

        <ImportHistory portfolioId={portfolioId} version={historyVersion} />
      </CardContent>
    </Card>
  );
}
