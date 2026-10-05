import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Visa Automatic",
  description: "Employee case management",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="app-header">
          <Link href="/cases" className="brand">
            <span className="brand-mark">VA</span>
            <span>
              <strong>Visa Automatic</strong>
              <small>Case management</small>
            </span>
          </Link>
          <nav aria-label="Primary navigation">
            <Link href="/cases">Cases</Link>
            <Link href="/cases/new" className="button button-small">
              New case
            </Link>
          </nav>
        </header>
        <main className="page-shell">{children}</main>
      </body>
    </html>
  );
}
