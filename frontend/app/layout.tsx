import type { Metadata } from "next";
import "./globals.css";

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
      <body>{children}</body>
    </html>
  );
}
