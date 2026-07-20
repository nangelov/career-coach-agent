"use client";

import Script from "next/script";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { fetchSession, type Session } from "@/lib/auth";
import { GA_MEASUREMENT_ID, isAnalyticsEnabled, trackPageview } from "@/lib/analytics";

/**
 * GA4 loader (design §6.27), rendered once in the root layout so it covers every route.
 *
 * **Loading gate (§6.22 / SEC-06):** the `gtag.js` script is injected only once an active
 * {@link Session} exists — a non-null session (guest or SSO) implies the one-time consent gate was
 * already accepted server-side to obtain it. On the pre-login screen (no session) nothing loads.
 * When `NEXT_PUBLIC_GA_MEASUREMENT_ID` is unset the component renders nothing at all (no script,
 * no `window.gtag`, no network calls).
 *
 * Pageviews: the initial one is sent by the `gtag('config', ...)` call below; subsequent App Router
 * navigations are tracked via {@link usePathname}. We deliberately do not read `useSearchParams`
 * (avoids forcing a Suspense boundary at build); path-level pageviews are sufficient for the
 * engagement metrics this phase needs.
 */
export default function Analytics() {
  const [session, setSession] = useState<Session | null>(null);
  const pathname = usePathname();
  const initialPageviewHandled = useRef(false);

  // Hydrate the session (same signal the pages use) so we can gate GA on its presence.
  useEffect(() => {
    if (!isAnalyticsEnabled()) {
      return;
    }
    let cancelled = false;
    void fetchSession().then((next) => {
      if (!cancelled) {
        setSession(next);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Fire a pageview on client-side route changes. Skip the first run once GA is live: the
  // `gtag('config', ...)` call already emits the initial pageview, so this avoids a duplicate.
  useEffect(() => {
    if (!isAnalyticsEnabled() || !session || !pathname) {
      return;
    }
    if (!initialPageviewHandled.current) {
      initialPageviewHandled.current = true;
      return;
    }
    trackPageview(pathname);
  }, [pathname, session]);

  if (!isAnalyticsEnabled() || !session) {
    return null;
  }

  return (
    <>
      <Script
        id="ga4-src"
        src={`https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`}
        strategy="afterInteractive"
      />
      <Script id="ga4-init" strategy="afterInteractive">
        {`window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
window.gtag = gtag;
gtag('js', new Date());
gtag('config', '${GA_MEASUREMENT_ID}');`}
      </Script>
    </>
  );
}
