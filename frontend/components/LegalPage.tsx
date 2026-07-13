import Link from "next/link";

import { POLICY_LAST_UPDATED, POLICY_VERSION } from "@/lib/policy";

/**
 * Shared shell for the static legal pages (Privacy Notice + Terms of Service, SEC-07).
 *
 * These pages are **public** — they must be readable *before* login, since the consent
 * checkbox on the login screen links here before any session exists (task constraint:
 * no auth gate, no chicken-and-egg with the consent gate). There is no middleware gating
 * page routes, so a plain server component is reachable unauthenticated.
 *
 * Renders a consistent header (title + visible policy version / last-updated, tied to
 * `POLICY_VERSION` ↔ backend `CONSENT_POLICY_VERSION`), the page body, and a footer that
 * links back to the app and across to the sibling policy.
 */
export interface LegalPageProps {
  title: string;
  /** Path of the sibling legal page to cross-link (e.g. "/privacy" from the terms page). */
  siblingHref: string;
  siblingLabel: string;
  children: React.ReactNode;
}

export default function LegalPage({
  title,
  siblingHref,
  siblingLabel,
  children,
}: LegalPageProps) {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-6 p-6">
      <header className="space-y-1 border-b border-gray-200 pb-4">
        <h1 className="text-2xl font-semibold">{title}</h1>
        <p className="text-sm text-gray-500">
          Version {POLICY_VERSION} · Last updated {POLICY_LAST_UPDATED}
        </p>
      </header>

      <article className="space-y-6 text-sm leading-6 text-gray-700 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-gray-900 [&_h2]:mt-2 [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-6 [&_a]:text-blue-600 [&_a]:underline">
        {children}
      </article>

      <footer className="mt-auto flex flex-wrap gap-4 border-t border-gray-200 pt-4 text-sm">
        <Link href="/" className="text-blue-600 underline hover:text-blue-700">
          Back to Career Coach
        </Link>
        <Link href={siblingHref} className="text-blue-600 underline hover:text-blue-700">
          {siblingLabel}
        </Link>
      </footer>
    </div>
  );
}
