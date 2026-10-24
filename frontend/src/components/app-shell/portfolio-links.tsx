import Link from "next/link";

export const destinations = [
  { path: "/", label: "Overview" },
  { path: "/holdings", label: "Reported Holdings" },
  { path: "/ledger", label: "Ledger Analytics" },
  { path: "/imports", label: "Imports" },
  { path: "/settings", label: "Account Settings" },
] as const;

export function PortfolioLinks({
  portfolioId,
  activePath,
  label,
}: {
  portfolioId: number | null;
  activePath?: string;
  label: string;
}) {
  return (
    <nav aria-label={label} className="flex flex-wrap gap-1">
      {destinations.map(({ path, label }) => {
        const active =
          activePath === path ||
          (path === "/ledger" && activePath?.startsWith("/portfolios/"));
        return (
          <Link
            key={path}
            href={`${path}${portfolioId == null ? "" : `?portfolio=${portfolioId}`}`}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground"}`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
