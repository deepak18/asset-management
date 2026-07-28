import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/app-shell/nav";
import { Providers } from "@/app/providers";

export const metadata: Metadata = {
  title: "Asset Management Terminal",
  description: "Local AI-powered investment research and portfolio analytics.",
};

/**
 * Root layout: global styles, the analytical-terminal chrome (top nav), and the
 * client Providers wrapper that boots mock mode when enabled. Kept as a Server
 * Component; only the interactive pieces (Nav, Providers) opt into the client.
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <Providers>
          <Nav />
          <main className="container py-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
