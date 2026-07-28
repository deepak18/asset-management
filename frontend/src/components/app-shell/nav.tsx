"use client";

import * as React from "react";
import { Moon, Sun, LineChart } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Top navigation bar. Holds the app identity and a light/dark toggle that flips
 * the `.dark` class on <html> (the switch the Tailwind theme tokens key off).
 * Theme state lives here rather than in a global store because it's the only
 * cross-cutting UI preference so far — promote to context when a second appears.
 */
export function Nav() {
  const [dark, setDark] = React.useState(false);

  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  return (
    <header className="border-b">
      <div className="container flex h-14 items-center justify-between">
        <div className="flex items-center gap-2">
          <LineChart className="h-5 w-5 text-primary" aria-hidden />
          <span className="font-semibold">Asset Management Terminal</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle theme"
          onClick={() => setDark((value) => !value)}
        >
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
    </header>
  );
}
