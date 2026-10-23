import * as React from "react";
import { apiClient, ApiError } from "@/lib/api-client";
import { env } from "@/lib/env";
import { useRetirementOperation, useRetirementResource } from "@/hooks/use-retirement";
import { formatMoney, formatQuantity } from "@/lib/format";
import type { ActivityFact, RetirementPreview } from "@/types/domain";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function ActivityList({
  facts,
  currency,
}: {
  facts: ActivityFact[];
  currency: string;
}) {
  return (
    <details>
      <summary>Inspect activity ({facts.length})</summary>
      {facts.length === 0 ? (
        <p>No activity supplied.</p>
      ) : (
        <Table aria-label="Source activity">
          <TableHeader>
            <TableRow>
              {[
                "Fund",
                "Dates",
                "Activity",
                "Units",
                "Price",
                "Amount",
                "External contribution",
                "Dividend",
                "Provenance",
              ].map((label) => (
                <TableHead key={label}>{label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {facts.map((fact, index) => (
              <TableRow key={`${fact.source_line}:${index}`}>
                <TableCell>{fact.fund_name}</TableCell>
                <TableCell>
                  Trade {fact.trade_date}
                  <br />
                  Run {fact.run_date}
                </TableCell>
                <TableCell>
                  {fact.code} · {fact.description} · {fact.kind}
                </TableCell>
                <TableCell>{formatQuantity(fact.quantity, 10)}</TableCell>
                <TableCell>{formatMoney(fact.price, currency)}</TableCell>
                <TableCell>{formatMoney(fact.amount, currency)}</TableCell>
                <TableCell>
                  {formatMoney(fact.external_contribution, currency)}
                </TableCell>
                <TableCell>{formatMoney(fact.dividend_amount, currency)}</TableCell>
                <TableCell>
                  <details>
                    <summary>Source line {fact.source_line}</summary>
                    <pre className="whitespace-pre-wrap">
                      {JSON.stringify(fact, null, 2)}
                    </pre>
                  </details>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </details>
  );
}

export function RetirementReview({ preview }: { preview: RetirementPreview }) {
  const currency = preview.options.currency;
  return (
    <section aria-label="Vanguard preview" className="space-y-3">
      <h3 className="font-semibold">Import review</h3>
      <p>
        Plan {preview.source.plan_number} · {preview.source.plan_name} · Source account{" "}
        {preview.source.account_number}
      </p>
      <p>
        As of {preview.options.as_of} · Reported total{" "}
        {formatMoney(preview.reported_total, currency)}
      </p>
      <p>
        Cost basis {formatMoney(preview.cost_basis, currency)} · Unrealized P&amp;L{" "}
        {formatMoney(preview.unrealized_pnl, currency)} · Returns unavailable
        (valuation-only).
      </p>
      <p role="note">
        {preview.options.history_complete
          ? "Inception history asserted; backend reconciliation still applies."
          : "Incomplete history: supplied activity does not establish opening lots."}{" "}
        Source amounts are retained, not recomputed. Reconciliation never enables
        returns.
      </p>
      <Table aria-label="Preview holdings">
        <TableHeader>
          <TableRow>
            {["Fund", "Units", "Reported price", "Reported value", "Source line"].map(
              (label) => (
                <TableHead key={label}>{label}</TableHead>
              ),
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {preview.source.holdings.map((holding, index) => (
            <TableRow key={`${holding.source_line}:${index}`}>
              <TableCell>{holding.fund_name}</TableCell>
              <TableCell>{formatQuantity(holding.quantity, 10)}</TableCell>
              <TableCell>{formatMoney(holding.reported_price, currency)}</TableCell>
              <TableCell>{formatMoney(holding.reported_value, currency)}</TableCell>
              <TableCell>
                {holding.source_line} · {holding.source_reference}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <h4 className="font-semibold">
        Security mappings (including activity-only funds)
      </h4>
      <ul>
        {preview.funds.map((fund) => (
          <li key={fund.alias_value}>
            {fund.fund_name} · {fund.ticker ?? "No confirmed ticker"} ·{" "}
            {fund.status === "WILL_CREATE_UNKNOWN"
              ? "Will create UNKNOWN security"
              : `Mapped security #${fund.security_id}`}{" "}
            · Alias {fund.alias_value}
          </li>
        ))}
      </ul>
      <ActivityList facts={preview.source.activity} currency={currency} />
      <Table aria-label="Share reconciliation">
        <TableHeader>
          <TableRow>
            {[
              "Fund",
              "Closing units",
              "Supported movement",
              "Implied prior units",
              "Status",
            ].map((label) => (
              <TableHead key={label}>{label}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {preview.reconciliation.map((row) => (
            <TableRow key={row.fund_name}>
              <TableCell>{row.fund_name}</TableCell>
              <TableCell>{formatQuantity(row.closing_units, 10)}</TableCell>
              <TableCell>{formatQuantity(row.net_supported_movement, 10)}</TableCell>
              <TableCell>{formatQuantity(row.implied_prior_units, 10)}</TableCell>
              <TableCell>{row.status} · Performance unavailable</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <h4 className="font-semibold">Issues</h4>
      {preview.issues.length === 0 ? (
        <p>No issues reported.</p>
      ) : (
        <ul>
          {preview.issues.map((issue, index) => (
            <li key={index}>
              {issue.blocking ? "Blocking" : "Warning"} · {issue.code} · {issue.message}
              {issue.fund_name ? ` · ${issue.fund_name}` : ""}
              {issue.source_line != null ? ` · Source line ${issue.source_line}` : ""}
            </li>
          ))}
        </ul>
      )}
      {!preview.can_commit && (
        <p role="alert">
          This preview cannot be committed. Resolve the backend issues and preview
          again.
        </p>
      )}
    </section>
  );
}

function ImportDetail({
  portfolioId,
  importId,
  version,
}: {
  portfolioId: number;
  importId: number;
  version: number;
}) {
  const detail = useRetirementResource(
    `detail:${portfolioId}:${importId}:${version}`,
    (signal) => apiClient.getRetirementImport(portfolioId, importId, signal),
  );
  if (detail.status === "loading") return <p role="status">Loading retained review…</p>;
  if (detail.status === "error") return <p role="alert">{detail.error.message}</p>;
  return <RetirementReview preview={detail.data.preview} />;
}

function RetirementRecords({
  portfolioId,
  refreshToken,
}: {
  portfolioId: number;
  refreshToken: number;
}) {
  const [retry, setRetry] = React.useState(0);
  const [inspect, setInspect] = React.useState<number | null>(null);
  const records = useRetirementResource(
    `records:${portfolioId}:${refreshToken}:${retry}`,
    async (signal) => {
      const [history, activity] = await Promise.all([
        apiClient.listRetirementImports(portfolioId, signal),
        apiClient.listAccountActivity(portfolioId, signal),
      ]);
      return { history, activity };
    },
  );
  return (
    <section aria-label="Retirement import history" className="space-y-3">
      <h3 className="font-semibold">Persisted imports and activity</h3>
      <Button variant="outline" onClick={() => setRetry((value) => value + 1)}>
        Reload Retirement History
      </Button>
      {records.status === "loading" && (
        <p role="status">Loading imports and account activity…</p>
      )}
      {records.status === "error" && <p role="alert">{records.error.message}</p>}
      {records.status === "success" && (
        <>
          {records.data.history.length === 0 ? (
            <p>No Vanguard imports yet.</p>
          ) : (
            <ul>
              {records.data.history.map((item) => (
                <li key={item.id}>
                  Import #{item.id} · {item.status ?? "COMMITTED"} · Holdings date{" "}
                  {item.preview.options.as_of} · Imported {item.imported_at}{" "}
                  <Button
                    variant="outline"
                    onClick={() => setInspect(inspect === item.id ? null : item.id)}
                    aria-expanded={inspect === item.id}
                  >
                    Inspect Import #{item.id}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <p>
            Persisted account activity: {records.data.activity.length} observed facts.
            Not a performance ledger.
          </p>
          {/* All activity is retained. The contract currently supports only USD imports. */}
          <ActivityList
            facts={records.data.activity.map((item) => item.fact)}
            currency="USD"
          />
        </>
      )}
      {inspect != null && (
        <ImportDetail
          key={`${portfolioId}:${inspect}:${refreshToken}:${retry}`}
          portfolioId={portfolioId}
          importId={inspect}
          version={refreshToken + retry}
        />
      )}
    </section>
  );
}

export function RetirementImportPanel(props: {
  portfolioId: number;
  refreshToken: number;
  onSuccess: () => void;
}) {
  return <ImportScope key={props.portfolioId} {...props} />;
}

function ImportScope({
  portfolioId,
  refreshToken,
  onSuccess,
}: {
  portfolioId: number;
  refreshToken: number;
  onSuccess: () => void;
}) {
  const uid = React.useId();
  const [file, setFile] = React.useState<File | null>(null);
  const [asOf, setAsOf] = React.useState("");
  const [historyComplete, setHistoryComplete] = React.useState(false);
  const [review, setReview] = React.useState<{
    preview: RetirementPreview;
    version: number;
  } | null>(null);
  const [acknowledged, setAcknowledged] = React.useState(false);
  const [pending, setPending] = React.useState<"preview" | "commit" | null>(null);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState("");
  const operation = useRetirementOperation(`${portfolioId}:${refreshToken}`);
  const preview = review?.version === refreshToken ? review.preview : null;
  // A sibling write invalidates tokens, but must not erase upload drafts.
  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPending(null);
  }, [refreshToken]);

  function invalidate() {
    setReview(null);
    setAcknowledged(false);
    setError("");
    setSuccess("");
  }
  function cancel() {
    operation.cancel();
    setPending(null);
    invalidate();
  }

  async function submit(kind: "preview" | "commit") {
    if (
      !file ||
      !asOf ||
      (kind === "commit" && (!preview?.can_commit || !acknowledged))
    )
      return;
    const controller = operation.start();
    if (!controller) return;
    const options = { as_of: asOf, currency: "USD", history_complete: historyComplete };
    setPending(kind);
    setError("");
    setSuccess("");
    if (kind === "preview") {
      setReview(null);
      setAcknowledged(false);
    }
    try {
      if (kind === "preview") {
        const result = await apiClient.previewRetirementImport(
          portfolioId,
          file,
          options,
          controller.signal,
        );
        if (operation.active(controller) && result.portfolio_id === portfolioId)
          setReview({ preview: result, version: refreshToken });
      } else if (preview) {
        await apiClient.commitRetirementImport(
          portfolioId,
          file,
          options,
          preview.preview_token,
          controller.signal,
        );
        if (!operation.active(controller)) return;
        setReview(null);
        setAcknowledged(false);
        setSuccess(
          "Vanguard import committed. Reported holdings, account settings, history and activity are refreshing.",
        );
        onSuccess();
      }
    } catch (err: unknown) {
      if (!operation.active(controller)) return;
      const conflict = err instanceof ApiError && err.status === 409;
      if (conflict) {
        setReview(null);
        setAcknowledged(false);
      }
      setError(
        `${err instanceof Error ? err.message : "Import failed."}${conflict ? " Create a new preview before confirming again; do not retry overlapping exports." : ""}`,
      );
    } finally {
      if (operation.active(controller)) setPending(null);
      operation.finish(controller);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Vanguard Retirement Import</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {env.apiMocking && (
          <p role="note">
            Mock mode: only the fictitious demo-retirement.csv fixture is supported.
            Arbitrary CSV parsing requires the live backend.
          </p>
        )}
        <p>
          Import current holdings plus observed activity. This is separate from
          Robinhood and does not create ledger purchases or returns.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit("preview");
          }}
          className="space-y-3"
        >
          <fieldset disabled={pending != null} className="space-y-3">
            <div>
              <Label htmlFor={`${uid}-file`}>Vanguard CSV</Label>
              <Input
                id={`${uid}-file`}
                type="file"
                accept=".csv,text/csv"
                onChange={(event) => {
                  invalidate();
                  setFile(event.target.files?.[0] ?? null);
                }}
              />
            </div>
            <div>
              <Label htmlFor={`${uid}-date`}>Holdings as of date</Label>
              <Input
                id={`${uid}-date`}
                type="date"
                required
                value={asOf}
                onChange={(event) => {
                  invalidate();
                  setAsOf(event.target.value);
                }}
              />
            </div>
            <div>
              <Label htmlFor={`${uid}-currency`}>Import currency</Label>
              <Input id={`${uid}-currency`} value="USD" readOnly />
            </div>
            <label className="block">
              <input
                type="checkbox"
                checked={historyComplete}
                onChange={(event) => {
                  invalidate();
                  setHistoryComplete(event.target.checked);
                }}
                aria-describedby={`${uid}-history-note`}
              />{" "}
              Includes All Transactions Since Inception
            </label>
            <p id={`${uid}-history-note`} className="text-sm text-muted-foreground">
              Leave unchecked for partial-period exports. Opting in asks the backend to
              validate history; it does not enable returns.
            </p>
            <Button type="submit" disabled={!file || !asOf}>
              {pending === "preview" ? "Previewing…" : "Preview Vanguard Import"}
            </Button>
          </fieldset>
        </form>
        {preview && (
          <>
            <RetirementReview preview={preview} />
            <label className="block">
              <input
                type="checkbox"
                disabled={pending != null}
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />{" "}
              I reviewed the source account, holdings, activity and issues
            </label>
            <Button
              disabled={pending != null || !acknowledged || !preview.can_commit}
              onClick={() => void submit("commit")}
            >
              {pending === "commit" ? "Importing…" : "Confirm Vanguard Import"}
            </Button>
          </>
        )}
        {(pending || preview) && (
          <Button variant="outline" onClick={cancel}>
            Cancel Vanguard Review
          </Button>
        )}
        {pending && (
          <p role="status">
            {pending === "commit" ? "Committing reviewed import…" : "Loading preview…"}
          </p>
        )}
        {error && <p role="alert">{error}</p>}
        {success && <p role="status">{success}</p>}
        <p className="text-sm text-muted-foreground">
          Cancellation dismisses browser results; an already-submitted commit may still
          complete on the server. Reload history before resubmitting.
        </p>
        <RetirementRecords portfolioId={portfolioId} refreshToken={refreshToken} />
      </CardContent>
    </Card>
  );
}
