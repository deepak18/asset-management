"use client";

import * as React from "react";
import { Moon, Sun, LineChart } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PortfolioSelector } from "@/components/portfolio/portfolio-selector";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { usePortfolioSelection } from "@/hooks/use-portfolio-selection";
import { PortfolioLinks } from "./portfolio-links";

/**
 * Top navigation bar. Holds the app identity, the portfolio picker, and a
 * light/dark toggle that flips the `.dark` class on <html> (the switch the
 * Tailwind theme tokens key off). Theme state lives here rather than in a global
 * store because it's the only cross-cutting UI preference so far — promote to
 * context when a second appears.
 */
export function Nav() {
  const pathname = usePathname();
  const { selectedId } = usePortfolioSelection();
  const detailId = /^\/portfolios\/(\d+)\/holdings\//.exec(pathname)?.[1];
  const navigationId = detailId == null ? selectedId : Number(detailId);
  const [dark, setDark] = React.useState(false);

  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  return (
    <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:rounded focus:bg-background focus:p-3 focus:ring-2"
      >
        Skip to content
      </a>
      <div className="container flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
        <Link
          href="/"
          className="flex items-center gap-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <LineChart className="h-5 w-5 text-primary" aria-hidden />
          <span className="font-semibold">Asset Management Terminal</span>
        </Link>
        <div className="flex min-w-0 items-center gap-2 [&>div]:min-w-0 [&>div]:flex-1 [&_select]:min-w-0 [&_select]:flex-1 [&_select]:w-auto">
          <PortfolioSelector />
          <Button
            variant="ghost"
            size="icon"
            aria-label="Toggle Theme"
            onClick={() => setDark((value) => !value)}
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </div>
      <div className="container pb-3">
        <PortfolioLinks
          portfolioId={navigationId}
          activePath={pathname}
          label="Primary navigation"
        />
      </div>
    </header>
  );
}
