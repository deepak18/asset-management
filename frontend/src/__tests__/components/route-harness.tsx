import "./router-state";
import * as React from "react";
import { vi } from "vitest";
import OverviewPage from "@/app/page";
import HoldingsPage from "@/app/holdings/page";
import LedgerPage from "@/app/ledger/page";
import ImportsPage from "@/app/imports/page";
import SettingsPage from "@/app/settings/page";
import { Nav } from "@/components/app-shell/nav";

// Simulate only Next's router boundary; feature pages and REST calls stay real.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a
      {...props}
      href={href}
      onClick={(event) => {
        props.onClick?.(event);
        if (!event.defaultPrevented && href?.startsWith("/")) {
          event.preventDefault();
          window.history.pushState(null, "", href);
          window.dispatchEvent(new PopStateEvent("popstate"));
        }
      }}
    >
      {children}
    </a>
  ),
}));

function subscribe(notify: () => void) {
  window.addEventListener("popstate", notify);
  return () => window.removeEventListener("popstate", notify);
}
export function RouteHarness() {
  const location = React.useSyncExternalStore(
    subscribe,
    () => window.location.pathname + window.location.search,
  );
  const path = location.split("?")[0];
  const Page =
    path === "/holdings"
      ? HoldingsPage
      : path === "/ledger"
        ? LedgerPage
        : path === "/imports"
          ? ImportsPage
          : path === "/settings"
            ? SettingsPage
            : OverviewPage;
  return (
    <>
      <Nav />
      <main id="main-content">
        <Page key={path} />
      </main>
    </>
  );
}
