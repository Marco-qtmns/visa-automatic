import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AuthShell } from "@/components/AuthShell";

import "./globals.css";

export const metadata: Metadata = {
  title: "Visa Automatic",
  description: "Employee case management",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthShell>{children}</AuthShell>
      </body>
    </html>
  );
}
