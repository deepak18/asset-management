"use client";

import * as React from "react";
import Link from "next/link";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingRows } from "@/components/shared/states";
import { useTransactions } from "@/hooks/use-portfolio";
import { apiClient, ApiError } from "@/lib/api-client";
import { DASH, formatMoney, formatQuantity } from "@/lib/format";
import type { Transaction, TransactionType } from "@/types/domain";
import { LEDGER_ORIGIN_LABELS } from "./ledger-origin";

function badgeVariant(type: TransactionType): "positive" | "negative" | "muted" {
  switch (type) {
    case "BUY":
      return "positive";
    case "SELL":
      return "negative";
    case "DIVIDEND":
    case "FEE":
    case "SPLIT":
      return "muted";
  }
}

function cellsFor(txn: Transaction) {
  switch (txn.type) {
    case "BUY":
    case "SELL":
      return {
        quantity: formatQuantity(txn.quantity),
        price: formatMoney(txn.price, txn.currency),
        amount: DASH,
      };
    case "DIVIDEND":
    case "FEE":
      return {
        quantity: DASH,
        price: DASH,
        amount: formatMoney(txn.amount, txn.currency),
      };
    case "SPLIT":
      return {
        quantity: `${formatQuantity(txn.split_ratio)}:1`,
        price: DASH,
        amount: DASH,
      };
  }
}

interface Selection {
  readonly portfolioId: number;
  readonly transaction: Transaction;
}

export function TransactionLedger(props: {
  portfolioId: number;
  refreshToken?: number;
  ticker?: string;
  onDeleted?: () => void;
}) {
  // Switching accounts unmounts the pending confirmation and discards late reads.
  return <LedgerForPortfolio key={props.portfolioId} {...props} />;
}

function LedgerForPortfolio({
  portfolioId,
  refreshToken = 0,
  ticker,
  onDeleted,
}: {
  portfolioId: number;
  refreshToken?: number;
  ticker?: string;
  onDeleted?: () => void;
}) {
  const [version, setVersion] = React.useState(0);
  const [selected, setSelected] = React.useState<Selection | null>(null);
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const submitting = React.useRef(false);
  const mounted = React.useRef(true);
  React.useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );
  const state = useTransactions(portfolioId, refreshToken + version);
  const transactions =
    state.status === "success"
      ? state.data.filter((row) => !ticker || row.ticker === ticker)
      : [];

  function dismiss() {
    if (submitting.current) return;
    setSelected(null);
  }
  async function confirm() {
    if (!selected || submitting.current) return;
    submitting.current = true;
    setPending(true);
    setError(null);
    const { portfolioId: account, transaction } = selected;
    try {
      await apiClient.deleteTransaction(account, transaction.id);
      if (!mounted.current) return;
      setSelected(null);
      setVersion((v) => v + 1);
      onDeleted?.();
    } catch (cause) {
      if (!mounted.current) return;
      if (cause instanceof ApiError && cause.status === 404) {
        setError(
          "Transaction no longer exists in this portfolio. Refreshing the ledger; review the row before trying again.",
        );
        setSelected(null);
        setVersion((v) => v + 1);
        onDeleted?.();
      } else if (cause instanceof ApiError && cause.status === 409) {
        setError(
          cause.detail ??
            "Deletion conflicts with an active import or dependent sale. Review the ledger first.",
        );
      } else {
        setError(
          cause instanceof Error
            ? cause.message
            : "Could not delete this transaction. Please try again.",
        );
      }
    } finally {
      submitting.current = false;
      if (mounted.current) setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Transaction ledger</CardTitle>
      </CardHeader>
      <CardContent>
        {error ? (
          <p role="alert" className="mb-3 text-destructive">
            {error}
          </p>
        ) : null}
        {state.status === "loading" ? (
          <LoadingRows rows={4} />
        ) : state.status === "error" ? (
          <ErrorState message="Could not load transactions." />
        ) : transactions.length === 0 ? (
          <EmptyState message="No transactions yet." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                {[
                  "ID",
                  "Date",
                  "Ticker",
                  "Type",
                  "Origin",
                  "Quantity",
                  "Price",
                  "Fees",
                  "Amount",
                  "Actions",
                ].map((label) => (
                  <TableHead key={label}>{label}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {transactions.map((txn) => {
                const cells = cellsFor(txn);
                return (
                  <TableRow key={txn.id} data-transaction-id={txn.id}>
                    <TableCell>{txn.id}</TableCell>
                    <TableCell>{txn.trade_date}</TableCell>
                    <TableCell>
                      <Link
                        className="underline"
                        href={`/portfolios/${portfolioId}/holdings/${encodeURIComponent(txn.ticker)}`}
                      >
                        {txn.ticker}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant={badgeVariant(txn.type)}>{txn.type}</Badge>
                    </TableCell>
                    <TableCell>{LEDGER_ORIGIN_LABELS[txn.history_origin]}</TableCell>
                    <TableCell>{cells.quantity}</TableCell>
                    <TableCell>{cells.price}</TableCell>
                    <TableCell>{formatMoney(txn.fees, txn.currency)}</TableCell>
                    <TableCell>{cells.amount}</TableCell>
                    <TableCell>
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label={`Delete ${txn.ticker} ${txn.type} Transaction ${txn.id}`}
                        onClick={() => {
                          setError(null);
                          setSelected({ portfolioId, transaction: txn });
                        }}
                      >
                        Delete
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <Dialog open={selected !== null} onClose={dismiss} title="Delete transaction?">
        {selected ? (
          <div className="space-y-4 text-sm">
            <p>
              Delete {selected.transaction.ticker} {selected.transaction.type} on{" "}
              {selected.transaction.trade_date} (
              {selected.transaction.type === "BUY" ||
              selected.transaction.type === "SELL"
                ? `${formatQuantity(selected.transaction.quantity)} shares`
                : selected.transaction.type === "SPLIT"
                  ? `${formatQuantity(selected.transaction.split_ratio)}:1 split`
                  : formatMoney(
                      selected.transaction.amount,
                      selected.transaction.currency,
                    )}
              ) from portfolio {selected.portfolioId}?
            </p>
            <p>
              Transaction {selected.transaction.id}:{" "}
              {LEDGER_ORIGIN_LABELS[selected.transaction.history_origin]}.
            </p>
            <p>
              Deletion changes calculated holdings and returns, may invalidate import
              retry safety, and marks this holding&apos;s history unconfirmed. The event
              leaves the active ledger but remains in the backend audit record. There is
              no undo.
            </p>
            <div className="flex gap-2">
              <Button variant="outline" disabled={pending} onClick={dismiss}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                disabled={pending}
                onClick={() => void confirm()}
              >
                {pending ? "Deleting…" : "Delete Transaction"}
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </Card>
  );
}
