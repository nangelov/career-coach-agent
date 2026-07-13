"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { fetchSession } from "@/lib/auth";

/**
 * SSO post-login landing page (design §7.1 / §7.2). As of SEC-04 the OIDC exchange completes
 * **server-side** in the BFF (`GET /api/auth/callback/{provider}`), which sets the httpOnly
 * session cookie and redirects the browser here with a **clean URL** (no token fragment).
 *
 * This page therefore no longer parses a token from the URL — it just confirms the cookie
 * took by hydrating from `GET /api/auth/session`, then routes to the chat. A failed hydration
 * (direct visit, cancelled login) shows an error with a link back to login.
 */
export default function AuthCallbackPage() {
  const router = useRouter();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchSession().then((session) => {
      if (cancelled) {
        return;
      }
      if (session) {
        router.replace("/");
      } else {
        setFailed(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="mx-auto flex h-screen w-full max-w-md flex-col items-center justify-center p-6 text-center">
      {failed ? (
        <div className="space-y-3" role="alert">
          <h1 className="text-xl font-semibold">Sign-in failed</h1>
          <p className="text-sm text-gray-500">
            We couldn&apos;t complete your sign-in. Please try again.
          </p>
          <Link className="text-blue-600 underline" href="/">
            Back to sign in
          </Link>
        </div>
      ) : (
        <p className="text-gray-500" role="status">
          Signing you in…
        </p>
      )}
    </div>
  );
}
