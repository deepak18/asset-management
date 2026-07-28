"use client";

import * as React from "react";

const STORAGE_KEY = "am.watchlist.tickers";

/** Normalize user input into a canonical ticker symbol (upper-case, trimmed). */
export function normalizeTicker(raw: string): string {
  return raw.trim().toUpperCase();
}

function read(): string[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      return [];
    }
    const parsed: unknown = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed.filter((t): t is string => typeof t === "string") : [];
  } catch {
    return [];
  }
}

export interface WatchlistController {
  tickers: string[];
  add: (raw: string) => void;
  remove: (ticker: string) => void;
}

/**
 * Watchlist state persisted to `localStorage`.
 *
 * The backend has no watchlist endpoint yet (arrives in a later phase), so this
 * is deliberately client-only — a clean seam to swap for a REST-backed hook
 * without touching the UI. Symbols are de-duplicated and stored upper-cased so
 * "aapl" and "AAPL" never both appear.
 */
export function useWatchlist(): WatchlistController {
  const [tickers, setTickers] = React.useState<string[]>([]);

  // Hydrate from storage after mount to stay SSR-safe (no window on the server).
  // Reading during render would diverge server ("[]") from client (stored list)
  // and trip a hydration mismatch, so this deliberate post-mount sync is exempt.
  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTickers(read());
  }, []);

  const add = React.useCallback((raw: string) => {
      const ticker = normalizeTicker(raw);
      if (ticker === "") {
        return;
      }
      setTickers((current) => {
        if (current.includes(ticker)) {
          return current;
        }
        const next = [...current, ticker];
        if (typeof window !== "undefined") {
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        }
        return next;
      });
    },
    [],
  );

  const remove = React.useCallback(
    (ticker: string) => {
      setTickers((current) => {
        const next = current.filter((t) => t !== ticker);
        if (typeof window !== "undefined") {
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        }
        return next;
      });
    },
    [],
  );

  return { tickers, add, remove };
}
