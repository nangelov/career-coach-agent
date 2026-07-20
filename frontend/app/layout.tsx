import type { Metadata } from "next";
import "./globals.css";

import Analytics from "@/components/Analytics";

export const metadata: Metadata = {
  title: "Career Coach v2",
  description: "AI career-coaching assistant — v2 rebuild.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        {/* GA4 loader (§6.27) — self-gates on a present session + configured Measurement ID. */}
        <Analytics />
        {children}
      </body>
    </html>
  );
}
