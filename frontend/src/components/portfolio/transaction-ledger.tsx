"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingRows } from "@/components/shared/states";
import { useTransactions } from "@/hooks/use-portfolio";
import { DASH, formatMoney, formatQuantity } from "@/lib/format";
import type { Transaction, TransactionType } from "@/types/domain";

/** Buy/Sell get colored badges; cash and structural events are neutral. */
function badgeVariant(type: TransactionType): "positive" | "negative" | "muted" | "default" {
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

/**
 * Which figures are meaningful for a given event type. Rendering "—" for the
 * irrelevant columns (e.g. price on a DIVIDEND) keeps the grid honest instead
 * of printing a default 0 that looks like real data.
 */
function cellsFor(txn: Transaction, currency: string): {
  quantity: string;
  price: string;
  amount: string;
} {
  switch (txn.type) {
    case "BUY":
    case "SELL":
      return {
        quantity: formatQuantity(txn.quantity),
        price: formatMoney(txn.price, currency),
        amount: DASH,
      };
    case "DIVIDEND":
    case "FEE":
      return { quantity: DASH, price: DASH, amount: formatMoney(txn.amount, currency) };
    case "SPLIT":
      return { quantity: `${formatQuantity(txn.split_ratio)}:1`, price: DASH, amount: DASH };
  }
}

function LedgerTable({ transactions }: { transactions: Transaction[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Date</TableHead>
          <TableHead>Ticker</TableHead>
          <TableHead>Type</TableHead>
          <TableHead className="text-right">Quantity</TableHead>
          <TableHead className="text-right">Price</TableHead>
          <TableHead className="text-right">Fees</TableHead>
          <TableHead className="text-right">Amount</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {transactions.map((txn, index) => {
          const cells = cellsFor(txn, txn.currency);
          return (
            <TableRow key={`${txn.ticker}-${txn.trade_date}-${txn.type}-${index}`}>
              <TableCell className="tabular-nums">{txn.trade_date}</TableCell>
              <TableCell className="font-medium">{txn.ticker}</TableCell>
              <TableCell>
                <Badge variant={badgeVariant(txn.type)}>{txn.type}</Badge>
              </TableCell>
              <TableCell className="text-right tabular-nums">{cells.quantity}</TableCell>
              <TableCell className="text-right tabular-nums">{cells.price}</TableCell>
              <TableCell className="text-right tabular-nums">
                {formatMoney(txn.fees, txn.currency)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{cells.amount}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/**
 * Transaction ledger grid. Reads the full ledger from the typed client and
 * renders each dated event. Loading, error, and empty-ledger states are all
 * handled explicitly. `refreshToken` forces a refetch after a write/import.
 */
export function TransactionLedger({
  portfolioId,
  refreshToken = 0,
}: {
  portfolioId: number;
  refreshToken?: number;
}) {
  const state = useTransactions(portfolioId, refreshToken);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Transaction ledger</CardTitle>
      </CardHeader>
      <CardContent>
        {state.status === "loading" ? (
          <LoadingRows rows={4} />
        ) : state.status === "error" ? (
          <ErrorState message="Could not load transactions." />
        ) : state.data.length === 0 ? (
          <EmptyState message="No transactions yet." />
        ) : (
          <LedgerTable transactions={state.data} />
        )}
      </CardContent>
    </Card>
  );
}
