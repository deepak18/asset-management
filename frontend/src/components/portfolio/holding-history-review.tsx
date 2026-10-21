"use client";

import * as React from "react";
import Link from "next/link";
import { apiClient, ApiError } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorState } from "@/components/shared/states";
import { HISTORY_REASONS } from "./holding-history";
import { ManualTransactionForm } from "./manual-transaction-form";
import { LEDGER_ORIGIN_LABELS } from "./ledger-origin";
import type { HoldingHistoryReview, PortfolioSummary } from "@/types/domain";

interface Props {
  portfolioId: number;
  ticker: string;
  refreshToken?: number;
  onChanged?: () => void;
}

/** Keyed scope and unmount-on-close isolate tokens, drafts and pending responses. */
export function HoldingHistoryReviewAction(props: Props) {
  return <ScopedAction key={`${props.portfolioId}:${props.ticker}`} {...props} />;
}

function ScopedAction(props: Props) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        aria-label={`Review History For ${props.ticker}`}
      >
        Review History
      </Button>
      {open ? <Review {...props} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

function Review({
  portfolioId,
  ticker,
  refreshToken = 0,
  onChanged,
  onClose,
}: Props & { onClose: () => void }) {
  const [review, setReview] = React.useState<HoldingHistoryReview | null>(null);
  const [portfolio, setPortfolio] = React.useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [ack, setAck] = React.useState(false);
  const [confirming, setConfirming] = React.useState(false);
  const [repairing, setRepairing] = React.useState(false);
  const reading = React.useRef<AbortController | null>(null);
  const writing = React.useRef<AbortController | null>(null);
  const ackId = React.useId();

  const load = React.useCallback(async () => {
    reading.current?.abort();
    const controller = new AbortController();
    reading.current = controller;
    setAck(false);
    setReview(null); // An old token must never remain actionable during a repair/refetch.
    setLoading(true);
    setError(null);
    try {
      const [snapshot, identity] = await Promise.all([
        apiClient.getHoldingHistory(portfolioId, ticker, controller.signal),
        apiClient.getPortfolio(portfolioId, controller.signal),
      ]);
      if (controller.signal.aborted) return;
      setReview(snapshot);
      setPortfolio(identity);
    } catch (err) {
      if (!controller.signal.aborted)
        setError(
          err instanceof ApiError
            ? err.message
            : "Could not load history. Please retry.",
        );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [portfolioId, ticker]);

  React.useEffect(() => {
    // Synchronize loading/token state with the selected server snapshot.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    return () => reading.current?.abort();
  }, [load, refreshToken]);
  React.useEffect(() => () => writing.current?.abort(), []);

  async function confirm() {
    if (
      !review ||
      !ack ||
      loading ||
      repairing ||
      writing.current ||
      review.blocking_gaps.length
    )
      return;
    const controller = new AbortController();
    writing.current = controller;
    setConfirming(true);
    setError(null);
    try {
      await apiClient.confirmHoldingHistory(
        portfolioId,
        ticker,
        { review_token: review.review_token, confirmed: true },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      onChanged?.();
      onClose();
      // The review is being dismissed; no success state or redundant GET is needed.
      controller.abort();
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.status === 409) {
        setNotice(
          "History changed or has blockers. Review the refreshed history and acknowledge again; confirmation was not retried.",
        );
        await load();
        if (!controller.signal.aborted) onChanged?.();
      } else {
        setError(
          err instanceof ApiError
            ? err.message
            : "Could not confirm history. Please retry.",
        );
      }
    } finally {
      if (!controller.signal.aborted) {
        writing.current = null;
        setConfirming(false);
      }
    }
  }

  // The shared minimal dialog traps buttons only. Include the review's links,
  // form controls and checkbox in its keyboard boundary without nesting modals.
  function trapFocus(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") return;
    event.stopPropagation();
    const focusable = [
      ...event.currentTarget.querySelectorAll<HTMLElement>(
        "button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled)",
      ),
    ].filter((element) => !element.matches(":disabled"));
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }

  return (
    <div onKeyDownCapture={trapFocus}>
      <Dialog
        open
        onClose={onClose}
        title={`Review history: ${ticker} — ${portfolio?.name ?? `Portfolio ${portfolioId}`} (portfolio ${portfolioId})`}
        className="max-h-[90vh] max-w-5xl overflow-y-auto"
      >
        <div className="space-y-4">
          <p>
            Compare dates, quantities, purchase cost, fees, dividends and splits with
            your actual broker records since first acquisition. Do not guess missing
            history.
          </p>
          <p>
            A position snapshot is not an actual purchase. Add the actual dated events,
            then remove the synthetic opening row through the holding ledger. Do not
            count both.
          </p>
          <Link
            className="underline"
            href={`/portfolios/${portfolioId}/holdings/${encodeURIComponent(ticker)}#holding-ledger`}
            onClick={onClose}
          >
            Open {ticker} holding detail ledger to inspect or delete records
          </Link>
          <p>
            For unresolved source events, use the import correction API; for failed or
            unfinished imports, inspect import history and repair/retry through the
            existing import surfaces/API. A checkbox cannot repair these blockers.
          </p>
          {notice ? <p role="status">{notice}</p> : null}
          {loading ? <p role="status">Loading history…</p> : null}
          {error ? <ErrorState message={error} /> : null}
          {!loading && !confirming && !repairing ? (
            <Button variant="outline" onClick={() => void load()}>
              Reload History / Retry
            </Button>
          ) : null}
          {review ? (
            <>
              <p role="status">
                {review.confirmed_at
                  ? `History confirmed / complete — ${review.confirmed_at}`
                  : review.history_complete
                    ? "History complete under backend policy; not explicitly confirmed (no confirmation timestamp)."
                    : "History not confirmed."}
              </p>
              {review.history_gaps.length ? (
                <ul className="list-disc pl-5" aria-label="History gaps">
                  {review.history_gaps.map((gap) => (
                    <li key={gap}>{HISTORY_REASONS[gap]}</li>
                  ))}
                </ul>
              ) : null}
              {review.blocking_gaps.length ? (
                <section aria-label="Confirmation blockers">
                  <h3 className="font-semibold">Repair required before confirmation</h3>
                  <ul className="list-disc pl-5">
                    {review.blocking_gaps.map((gap) => (
                      <li key={gap}>{HISTORY_REASONS[gap]}</li>
                    ))}
                  </ul>
                  <p>
                    Add or correct actual broker events, remove synthetic snapshots in
                    the ledger, or resolve/retry the relevant import, then reload
                    history.
                  </p>
                </section>
              ) : null}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption>
                    Full active ledger snapshot for {ticker}; each row shows its
                    explicit currency. Values are backend decimal strings.
                  </caption>
                  <thead>
                    <tr>
                      {[
                        "ID",
                        "Date",
                        "Type",
                        "Origin",
                        "Currency",
                        "Quantity",
                        "Price / share",
                        "Fees",
                        "Amount",
                        "Split ratio",
                      ].map((label) => (
                        <th scope="col" key={label}>
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {review.transactions.map((row) => (
                      <tr key={row.id} data-transaction-id={row.id}>
                        {[
                          row.id,
                          row.trade_date,
                          row.type,
                          LEDGER_ORIGIN_LABELS[row.history_origin],
                          row.currency,
                          row.quantity,
                          row.price,
                          row.fees,
                          row.amount,
                          row.split_ratio,
                        ].map((value, index) => (
                          <td key={index}>{value ?? "—"}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!review.transactions.length ? (
                  <p>No active transactions in this snapshot.</p>
                ) : null}
              </div>
            </>
          ) : null}
          {portfolio ? (
            <fieldset disabled={confirming || loading || repairing}>
              <ManualTransactionForm
                portfolioId={portfolioId}
                currency={portfolio.base_currency}
                lockedTicker={ticker}
                onPendingChange={(pending) => {
                  setRepairing(pending);
                  if (pending) {
                    setAck(false);
                    setReview(null);
                  }
                }}
                onSuccess={() => {
                  setNotice(
                    "Transaction added. Compare the refreshed ledger and acknowledge again.",
                  );
                  void load();
                  onChanged?.();
                }}
              />
            </fieldset>
          ) : null}
          <div className="space-x-2">
            <input
              id={ackId}
              type="checkbox"
              checked={ack}
              disabled={
                !review ||
                loading ||
                confirming ||
                repairing ||
                !!review.blocking_gaps.length
              }
              onChange={(event) => setAck(event.target.checked)}
            />
            <label htmlFor={ackId}>
              I compared this snapshot with my broker records and confirm complete
              transactions since first acquisition, including all buys, sells, fees,
              dividends, other cash events and splits.
            </label>
          </div>
          <Button
            disabled={
              !review ||
              !ack ||
              loading ||
              confirming ||
              repairing ||
              !!review.blocking_gaps.length
            }
            onClick={() => void confirm()}
          >
            {confirming ? "Confirming…" : "Confirm History"}
          </Button>{" "}
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
