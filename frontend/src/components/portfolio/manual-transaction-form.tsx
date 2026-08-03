"use client";

import * as React from "react";
import { apiClient, ApiError } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ErrorState } from "@/components/shared/states";
import type { LedgerIngestResult, TransactionInput, TransactionType } from "@/types/domain";

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
}: {
  portfolioId: number;
  currency?: string;
  onSuccess?: () => void;
}) {
  const [ticker, setTicker] = React.useState("");
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
    setTicker("");
    setTradeDate("");
    setQuantity("");
    setPrice("");
    setFees("");
    setAmount("");
    setSplitRatio("");
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

    setSubmitting(true);
    try {
      const ingest = await apiClient.addTransactions(portfolioId, [txn]);
      setResult(ingest);
      resetFields();
      onSuccess?.();
    } catch (err) {
      setError(
        err instanceof ApiError ? (err.detail ?? err.message) : "Could not add the transaction.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add transaction</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="txn-ticker">Ticker</Label>
            <Input
              id="txn-ticker"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="AAPL"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="txn-type">Type</Label>
            <Select
              id="txn-type"
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
            <Label htmlFor="txn-date">Trade date</Label>
            <Input
              id="txn-date"
              type="date"
              value={tradeDate}
              onChange={(e) => setTradeDate(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="txn-currency">Currency</Label>
            <Select
              id="txn-currency"
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
                <Label htmlFor="txn-quantity">Quantity</Label>
                <Input
                  id="txn-quantity"
                  inputMode="decimal"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  placeholder="10"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="txn-price">Price / share</Label>
                <Input
                  id="txn-price"
                  inputMode="decimal"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder="185.50"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="txn-fees">Fees (optional)</Label>
                <Input
                  id="txn-fees"
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
              <Label htmlFor="txn-amount">Amount</Label>
              <Input
                id="txn-amount"
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="2.40"
              />
            </div>
          ) : null}

          {isSplit ? (
            <div className="space-y-1.5">
              <Label htmlFor="txn-split">Split ratio</Label>
              <Input
                id="txn-split"
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
              {submitting ? "Adding…" : "Add transaction"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
