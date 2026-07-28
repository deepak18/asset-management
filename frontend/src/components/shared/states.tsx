import * as React from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Reusable state blocks so every panel renders loading / error / empty the same
 * way. Centralizing them keeps the "honest empty state" rule (§1.4: show a real
 * message, never a fake 0) consistent across the dashboard.
 */

export function LoadingRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-6 w-full" />
      ))}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

export function EmptyState({
  message,
  className,
}: {
  message: string;
  className?: string;
}) {
  return (
    <p className={cn("text-sm text-muted-foreground", className)}>{message}</p>
  );
}
