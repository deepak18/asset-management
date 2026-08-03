"use client";

import * as React from "react";
import { apiClient, ApiError } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ErrorState } from "@/components/shared/states";
import type { LedgerIngestResult, PositionSnapshot } from "@/types/domain";

const CURRENCIES = ["USD", "INR"] as const;

/**
 * Snapshot entry form (§1 on-ramp): record a *current* holding without keying in
 * its full trade history. The backend turns it into a single opening BUY lot.
 *
 * Cost basis must be given exactly one of two ways — per share OR total — never
 * both (the API returns 422 if both are set), so we model it as one "basis mode"
 * selector feeding one amount field, which makes "both" unrepresentable in the
 * UI. We also spell out the trade-off: a snapshot leaves money-weighted return
 * (XIRR) undefined; importing full history is what enables it.
 */
export function AddPositionForm({
  portfolioId,
  currency: baseCurrency = "USD",
  onSuccess,
}: {
  portfolioId: number;
  currency?: string;
  onSuccess?: () => void;
}) {
  const [ticker, setTicker] = React.useState("");
  const [quantity, setQuantity] = React.useState("");
  const [currency, setCurrency] = React.useState(baseCurrency);
  const [asOf, setAsOf] = React.useState("");
  const [sector, setSector] = React.useState("");
  const [industry, setIndustry] = React.useState("");
  const [basisMode, setBasisMode] = React.useState<"per_share" | "total">("per_share");
  const [basisAmount, setBasisAmount] = React.useState("");

  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<LedgerIngestResult | null>(null);

  function resetFields() {
    setTicker("");
    setQuantity("");
    setAsOf("");
    setSector("");
    setIndustry("");
    setBasisAmount("");
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);

    const trimmedTicker = ticker.trim().toUpperCase();
    if (trimmedTicker === "") {
      setError("Ticker is required.");
      return;
    }
    if (quantity.trim() === "") {
      setError("Quantity is required.");
      return;
    }

    const snapshot: PositionSnapshot = {
      ticker: trimmedTicker,
      quantity: quantity.trim(),
      currency,
      as_of: asOf.trim() === "" ? null : asOf.trim(),
      sector: sector.trim() === "" ? null : sector.trim(),
      industry: industry.trim() === "" ? null : industry.trim(),
    };
    // Send exactly the chosen basis field — never both — so we can't trip 422.
    if (basisAmount.trim() !== "") {
      if (basisMode === "per_share") {
        snapshot.cost_basis_per_share = basisAmount.trim();
      } else {
        snapshot.total_cost_basis = basisAmount.trim();
      }
    }

    setSubmitting(true);
    try {
      const ingest = await apiClient.addPositions(portfolioId, [snapshot]);
      setResult(ingest);
      resetFields();
      onSuccess?.();
    } catch (err) {
      setError(
        err instanceof ApiError ? (err.detail ?? err.message) : "Could not add the position.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add current position</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-4 text-xs text-muted-foreground">
          A snapshot records today&apos;s holding as one opening lot — cost-basis and
          unrealized P&amp;L stay exact, but money-weighted return (XIRR) is left
          undefined. Import your full history to enable XIRR.
        </p>
        <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="pos-ticker">Ticker</Label>
            <Input
              id="pos-ticker"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="AAPL"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pos-quantity">Quantity</Label>
            <Input
              id="pos-quantity"
              inputMode="decimal"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="10"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pos-currency">Currency</Label>
            <Select
              id="pos-currency"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pos-asof">Acquired on (optional)</Label>
            <Input
              id="pos-asof"
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pos-basis-mode">Cost basis</Label>
            <Select
              id="pos-basis-mode"
              aria-label="Cost basis type"
              value={basisMode}
              onChange={(e) => setBasisMode(e.target.value as "per_share" | "total")}
            >
              <option value="per_share">Per share</option>
              <option value="total">Total invested</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pos-basis-amount">
              {basisMode === "per_share" ? "Cost per share" : "Total cost basis"} (optional)
            </Label>
            <Input
              id="pos-basis-amount"
              inputMode="decimal"
              value={basisAmount}
              onChange={(e) => setBasisAmount(e.target.value)}
              placeholder={basisMode === "per_share" ? "185.50" : "1855.00"}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pos-sector">Sector (optional)</Label>
            <Input
              id="pos-sector"
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              placeholder="Technology"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pos-industry">Industry (optional)</Label>
            <Input
              id="pos-industry"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="Consumer Electronics"
            />
          </div>

          {error ? (
            <div className="sm:col-span-2">
              <ErrorState message={error} />
            </div>
          ) : null}
          {result ? (
            <p className="text-sm text-positive sm:col-span-2" role="status">
              Recorded {result.created_transactions} lot
              {result.created_transactions === 1 ? "" : "s"}
              {result.tickers.length > 0 ? ` for ${result.tickers.join(", ")}` : ""}.
            </p>
          ) : null}

          <div className="sm:col-span-2">
            <Button type="submit" disabled={submitting}>
              {submitting ? "Adding…" : "Add position"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
