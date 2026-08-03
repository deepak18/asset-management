import { Dashboard } from "@/components/portfolio/dashboard";

/**
 * Unified Portfolio Dashboard (§1.4). The portfolio shown is chosen in the app
 * shell picker (persisted in localStorage) and shared via the selection context,
 * so this page is just a thin mount point for the client {@link Dashboard}.
 */
export default function DashboardPage() {
  return <Dashboard />;
}
