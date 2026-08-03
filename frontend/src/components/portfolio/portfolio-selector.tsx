"use client";

import { usePortfolioSelection } from "@/hooks/use-portfolio-selection";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { CreatePortfolioDialog } from "@/components/portfolio/create-portfolio-dialog";

/**
 * Portfolio picker mounted in the app shell.
 *
 * Reads the shared selection context (list + selected id) so the whole dashboard
 * follows the chosen portfolio — the old hard-coded id 1 is gone. When the user
 * has no portfolios yet, it degrades to a single "Create portfolio" call to
 * action instead of an empty dropdown.
 */
export function PortfolioSelector() {
  const { status, portfolios, selectedId, select } = usePortfolioSelection();

  if (status === "loading") {
    return <Skeleton className="h-9 w-48" />;
  }
  if (status === "error") {
    return <span className="text-sm text-destructive">Portfolios unavailable</span>;
  }
  if (portfolios.length === 0) {
    return <CreatePortfolioDialog triggerLabel="Create portfolio" triggerVariant="default" />;
  }

  return (
    <div className="flex items-center gap-2">
      <Select
        aria-label="Select portfolio"
        className="w-56"
        value={selectedId ?? ""}
        onChange={(e) => select(Number(e.target.value))}
      >
        {portfolios.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} · {p.base_currency}
          </option>
        ))}
      </Select>
      <CreatePortfolioDialog />
    </div>
  );
}
