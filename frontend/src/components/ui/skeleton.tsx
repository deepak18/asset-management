import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Pulsing placeholder used as the loading state for cards, rows, and charts.
 * A shared primitive keeps every panel's "loading" look identical.
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

export { Skeleton };
