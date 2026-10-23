"use client";

import type { SecurityInfo, ValuationView } from "@/types/domain";
import { formatMoney, formatQuantity } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function ReportedHoldings({
  valuation,
  securities,
}: {
  valuation: ValuationView;
  securities: SecurityInfo[];
}) {
  const snapshot = valuation.snapshot;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Reported Holdings</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {!snapshot ? (
          <p>
            No reported snapshot yet. Choose a Vanguard CSV and an explicit holdings
            date below to preview an import.
          </p>
        ) : (
          <>
            <p>
              Reported balance{" "}
              <strong className="text-2xl">
                {formatMoney(snapshot.reported_total, snapshot.currency)}
              </strong>
            </p>
            <p>
              {valuation.status} · As of {snapshot.as_of} ·{" "}
              {snapshot.provenance.source_code} ·{" "}
              {snapshot.provenance.source_reference ?? "Source reference unavailable"} ·
              Imported {snapshot.provenance.imported_at}
            </p>
            {valuation.status === "PARTIAL" && (
              <p role="note">
                Partial snapshot: this total covers only the reported positions, not the
                whole account.
              </p>
            )}
            <p>
              VALUATION_ONLY: returns unavailable. Cost basis{" "}
              {formatMoney(snapshot.cost_basis, snapshot.currency)}; unrealized P&amp;L{" "}
              {formatMoney(snapshot.unrealized_pnl, snapshot.currency)}. Reported values
              are retained, not recomputed from rounded units and prices.
            </p>
            <Table aria-label="Reported holdings">
              <TableHeader>
                <TableRow>
                  {[
                    "Security",
                    "Units",
                    "Reported price",
                    "Reported value",
                    "Cost basis",
                    "Unrealized P&L",
                    "Source",
                  ].map((label) => (
                    <TableHead key={label}>{label}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {snapshot.positions.map((position) => {
                  const security = securities.find(
                    (item) => item.id === position.security_id,
                  );
                  return (
                    <TableRow key={position.security_id}>
                      <TableCell>
                        {security?.name ?? `Unknown security #${position.security_id}`}
                        <br />
                        {security?.ticker ?? "No confirmed ticker"} ·{" "}
                        {security?.instrument_type ?? "UNKNOWN"}
                      </TableCell>
                      <TableCell>{formatQuantity(position.quantity, 10)}</TableCell>
                      <TableCell>
                        {formatMoney(position.reported_price, snapshot.currency)}
                      </TableCell>
                      <TableCell>
                        {formatMoney(position.reported_value, snapshot.currency)}
                      </TableCell>
                      <TableCell>
                        {formatMoney(position.cost_basis, snapshot.currency)}
                      </TableCell>
                      <TableCell>
                        {formatMoney(position.unrealized_pnl, snapshot.currency)}
                      </TableCell>
                      <TableCell>
                        {position.provenance.as_of} · {position.provenance.source_code}{" "}
                        · {position.provenance.source_reference ?? "—"}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </>
        )}
        <p className="text-sm text-muted-foreground">
          Reported snapshots and Ledger Analytics are separate views. Never add their
          balances together. Observed activity is explanatory history, not additional
          holdings or acquisition lots.
        </p>
      </CardContent>
    </Card>
  );
}
