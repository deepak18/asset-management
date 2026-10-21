"use client";

import * as React from "react";
import { Pencil } from "lucide-react";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { ClassificationCombobox } from "./classification-combobox";
import type { HoldingInfo } from "@/types/domain";

/** One ticker, one field: omitted fields are preserved and blank explicitly clears. */
export function HoldingClassificationCell({
  portfolioId,
  holding,
  field,
  suggestions = [],
  onChanged,
}: {
  portfolioId: number;
  holding: HoldingInfo;
  field: "sector" | "industry";
  suggestions?: readonly string[];
  onChanged: (holding: HoldingInfo) => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const controller = React.useRef<AbortController | null>(null);
  React.useEffect(() => () => controller.current?.abort(), []);
  const label = `${holding.ticker} ${field}`;
  const actionLabel = `${holding.ticker} ${field === "sector" ? "Sector" : "Industry"}`;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (saving) return;
    const request = new AbortController();
    controller.current = request;
    setSaving(true);
    setError(null);
    try {
      const updated = await apiClient.updateHoldingClassification(
        portfolioId,
        holding.ticker,
        { [field]: draft.trim() || null },
        request.signal,
      );
      if (request.signal.aborted) return;
      setEditing(false);
      onChanged(updated);
    } catch (err) {
      if (!request.signal.aborted)
        setError(err instanceof Error ? err.message : "Could not save classification.");
    } finally {
      if (!request.signal.aborted) setSaving(false);
    }
  }

  if (!editing)
    return (
      <div className="flex items-center gap-2">
        <span>{holding[field] || "Not classified"}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={`Edit ${actionLabel}`}
          onClick={() => {
            setDraft(holding[field] ?? "");
            setError(null);
            setEditing(true);
          }}
        >
          <Pencil className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    );

  return (
    <form onSubmit={(event) => void save(event)} className="space-y-2">
      <ClassificationCombobox
        label={label}
        value={draft}
        suggestions={suggestions}
        disabled={saving}
        invalid={error !== null}
        onChange={setDraft}
      />
      <p className="text-xs text-muted-foreground">
        Leave blank to clear this {field}.
      </p>
      <div className="flex gap-1">
        <Button
          type="submit"
          size="sm"
          disabled={saving}
          aria-label={`${saving ? "Saving…" : "Save"} ${actionLabel}`}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={saving}
          onClick={() => setEditing(false)}
        >
          Cancel
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}
