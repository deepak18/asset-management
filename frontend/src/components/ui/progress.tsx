import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Determinate / indeterminate progress bar.
 *
 * Pass `value`/`max` for a known ratio; omit `value` (or pass null) for the
 * *indeterminate* state — a pulsing full-width track we render while the backend
 * has not yet counted `total_rows`. Showing an honest "unknown" bar beats a fake
 * denominator that would make the fill jump backwards once the real count lands.
 */
export function Progress({
  value,
  max = 100,
  className,
  label,
}: {
  value?: number | null;
  max?: number;
  className?: string;
  label?: string;
}) {
  const indeterminate = value == null;
  const pct = indeterminate ? 100 : Math.min(100, Math.max(0, (value / (max || 1)) * 100));

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={indeterminate ? undefined : max}
      aria-valuenow={indeterminate ? undefined : value}
      className={cn("h-2 w-full overflow-hidden rounded-full bg-muted", className)}
    >
      <div
        className={cn(
          "h-full rounded-full bg-primary transition-all",
          indeterminate && "animate-pulse",
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
