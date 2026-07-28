"use client";

import * as React from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/shared/states";
import { useWatchlist } from "@/hooks/use-watchlist";

/**
 * Watchlist manager: add/remove tickers the user wants to track.
 *
 * State is client-only (localStorage) because the backend has no watchlist
 * endpoint yet — a deliberate seam that will swap for a REST-backed hook later
 * without changing this component. Symbols are normalized (upper-case, unique).
 */
export function Watchlist() {
  const { tickers, add, remove } = useWatchlist();
  const [draft, setDraft] = React.useState("");

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    add(draft);
    setDraft("");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Watchlist</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <Input
            aria-label="Add ticker"
            placeholder="Add ticker (e.g. NVDA)"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <Button type="submit" size="sm">
            Add
          </Button>
        </form>

        {tickers.length === 0 ? (
          <EmptyState message="Your watchlist is empty." />
        ) : (
          <ul className="flex flex-wrap gap-2">
            {tickers.map((ticker) => (
              <li key={ticker}>
                <Badge variant="outline" className="gap-1 pr-1">
                  <span className="font-medium">{ticker}</span>
                  <button
                    type="button"
                    aria-label={`Remove ${ticker}`}
                    onClick={() => remove(ticker)}
                    className="rounded-sm p-0.5 hover:bg-muted"
                  >
                    <X className="h-3 w-3" aria-hidden />
                  </button>
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
