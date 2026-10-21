"use client";

import * as React from "react";
import { apiClient, ApiError } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ErrorState } from "@/components/shared/states";
import type {
  LedgerIngestResult,
  TransactionInput,
  TransactionType,
} from "@/types/domain";

const CURRENCIES = ["USD", "INR"] as const;
const TYPES: TransactionType[] = ["BUY", "SELL", "DIVIDEND", "FEE", "SPLIT"];

/**
 * Manual single-transaction entry. The visible fields follow the chosen `type`
 * so the user never fills in an irrelevant box:
 *
 * * BUY / SELL → quantity, price, fees
 * * DIVIDEND / FEE → amount
 * * SPLIT → split ratio
 *
 * Only the relevant fields are sent; the rest keep their contract defaults.
 */
export function ManualTransactionForm({
  portfolioId,
  currency: baseCurrency = "USD",
  onSuccess,
  lockedTicker,
  onPendingChange,
}: {
  portfolioId: number;
  currency?: string;
  onSuccess?: () => void;
  lockedTicker?: string;
  onPendingChange?: (pending: boolean) => void;
}) {
  const id = React.useId();
  const request = React.useRef<AbortController | null>(null);
  React.useEffect(() => () => request.current?.abort(), []);
  const [ticker, setTicker] = React.useState(lockedTicker ?? "");
  const [type, setType] = React.useState<TransactionType>("BUY");
  const [tradeDate, setTradeDate] = React.useState("");
  const [currency, setCurrency] = React.useState(baseCurrency);
  const [quantity, setQuantity] = React.useState("");
  const [price, setPrice] = React.useState("");
  const [fees, setFees] = React.useState("");
  const [amount, setAmount] = React.useState("");
  const [splitRatio, setSplitRatio] = React.useState("");

  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<LedgerIngestResult | null>(null);

  const isTrade = type === "BUY" || type === "SELL";
  const isCash = type === "DIVIDEND" || type === "FEE";
  const isSplit = type === "SPLIT";

  function resetFields() {
    setTicker(lockedTicker ?? "");
    setTradeDate("");
    setQuantity("");
    setPrice("");
    setFees("");
    setAmount("");
    setSplitRatio("");
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (request.current) return;
    setError(null);
    setResult(null);

    const trimmedTicker = (lockedTicker ?? ticker).trim().toUpperCase();
    if (trimmedTicker === "") {
      setError("Ticker is required.");
      return;
    }
    if (tradeDate.trim() === "") {
      setError("Trade date is required.");
      return;
    }

    const txn: TransactionInput = {
      ticker: trimmedTicker,
      type,
      trade_date: tradeDate,
      currency,
      // Contract defaults; only the type-relevant ones are overwritten below.
      quantity: "0",
      price: "0",
      fees: "0",
      amount: "0",
      split_ratio: "1",
    };
    if (isTrade) {
      txn.quantity = quantity.trim() === "" ? "0" : quantity.trim();
      txn.price = price.trim() === "" ? "0" : price.trim();
      if (fees.trim() !== "") {
        txn.fees = fees.trim();
      }
    } else if (isCash) {
      txn.amount = amount.trim() === "" ? "0" : amount.trim();
    } else if (isSplit) {
      txn.split_ratio = splitRatio.trim() === "" ? "1" : splitRatio.trim();
    }

    const controller = new AbortController();
    request.current = controller;
    setSubmitting(true);
    onPendingChange?.(true);
    try {
      const ingest = await apiClient.addTransactions(
        portfolioId,
        [txn],
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setResult(ingest);
      resetFields();
      onSuccess?.();
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(
        err instanceof ApiError
          ? (err.detail ?? err.message)
          : "Could not add the transaction.",
      );
    } finally {
      if (!controller.signal.aborted) {
        request.current = null;
        setSubmitting(false);
        onPendingChange?.(false);
      }
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {lockedTicker ? "Add missing transaction" : "Add transaction"}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor={`${id}-txn-ticker`}>Ticker</Label>
            <Input
              id={`${id}-txn-ticker`}
              readOnly={lockedTicker != null}
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="AAPL"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${id}-txn-type`}>Type</Label>
            <Select
              id={`${id}-txn-type`}
              value={type}
              onChange={(e) => setType(e.target.value as TransactionType)}
            >
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${id}-txn-date`}>Trade date</Label>
            <Input
              id={`${id}-txn-date`}
              required={lockedTicker != null}
              type="date"
              value={tradeDate}
              onChange={(e) => setTradeDate(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${id}-txn-currency`}>Currency</Label>
            <Select
              id={`${id}-txn-currency`}
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

          {isTrade ? (
            <>
              <div className="space-y-1.5">
                <Label htmlFor={`${id}-txn-quantity`}>Quantity</Label>
                <Input
                  id={`${id}-txn-quantity`}
                  required={lockedTicker != null}
                  inputMode="decimal"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  placeholder="10"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor={`${id}-txn-price`}>Price / share</Label>
                <Input
                  id={`${id}-txn-price`}
                  required={lockedTicker != null}
                  inputMode="decimal"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder="185.50"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor={`${id}-txn-fees`}>Fees (optional)</Label>
                <Input
                  id={`${id}-txn-fees`}
                  inputMode="decimal"
                  value={fees}
                  onChange={(e) => setFees(e.target.value)}
                  placeholder="1.00"
                />
              </div>
            </>
          ) : null}

          {isCash ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-txn-amount`}>Amount</Label>
              <Input
                id={`${id}-txn-amount`}
                required={lockedTicker != null}
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="2.40"
              />
            </div>
          ) : null}

          {isSplit ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-txn-split`}>Split ratio</Label>
              <Input
                id={`${id}-txn-split`}
                required={lockedTicker != null}
                inputMode="decimal"
                value={splitRatio}
                onChange={(e) => setSplitRatio(e.target.value)}
                placeholder="2"
              />
            </div>
          ) : null}

          {error ? (
            <div className="sm:col-span-2">
              <ErrorState message={error} />
            </div>
          ) : null}
          {result ? (
            <p className="text-sm text-positive sm:col-span-2" role="status">
              Recorded {result.created_transactions} transaction
              {result.created_transactions === 1 ? "" : "s"}.
            </p>
          ) : null}

          <div className="sm:col-span-2">
            <Button type="submit" disabled={submitting}>
              {submitting ? "Recording…" : "Add Transaction"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
