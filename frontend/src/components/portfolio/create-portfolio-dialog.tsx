"use client";

import * as React from "react";
import { Plus } from "lucide-react";
import { apiClient, ApiError } from "@/lib/api-client";
import { usePortfolioSelection } from "@/hooks/use-portfolio-selection";
import { Button, type ButtonProps } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ErrorState } from "@/components/shared/states";

/** Currencies the platform is built for (USD live now, INR next — PLAN §8). */
const CURRENCIES = ["USD", "INR"] as const;

/**
 * Create-portfolio dialog. Submits `POST /api/v1/portfolios`, then reloads the
 * picker list and auto-selects the new portfolio so the dashboard jumps straight
 * to it. Renders its own trigger button; the "no portfolios yet" prompt reuses
 * this with a louder label.
 */
export function CreatePortfolioDialog({
  triggerLabel = "New portfolio",
  triggerVariant = "outline",
}: {
  triggerLabel?: string;
  triggerVariant?: ButtonProps["variant"];
}) {
  const { reloadAndSelect } = usePortfolioSelection();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [currency, setCurrency] = React.useState<string>("USD");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  function reset() {
    setName("");
    setCurrency("USD");
    setError(null);
    setSubmitting(false);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === "") {
      setError("Name is required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await apiClient.createPortfolio({
        name: trimmed,
        base_currency: currency,
      });
      await reloadAndSelect(created.id);
      setOpen(false);
      reset();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? (err.detail ?? err.message)
          : "Could not create portfolio.",
      );
      setSubmitting(false);
    }
  }

  return (
    <>
      <Button
        variant={triggerVariant}
        size="sm"
        onClick={() => setOpen(true)}
        className="gap-1"
      >
        <Plus className="h-4 w-4" aria-hidden />
        {triggerLabel}
      </Button>

      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
          reset();
        }}
        title="Create portfolio"
        description="Name the book and pick its reporting base currency."
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="portfolio-name">Name</Label>
            <Input
              id="portfolio-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Growth Portfolio"
              maxLength={120}
              autoFocus
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="portfolio-currency">Base currency</Label>
            <Select
              id="portfolio-currency"
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

          {error ? <ErrorState message={error} /> : null}

          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setOpen(false);
                reset();
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Creating…" : "Create"}
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
