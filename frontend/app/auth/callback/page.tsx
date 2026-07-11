"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { saveSession, sessionFromFragment } from "@/lib/auth";

/**
 * SSO post-login landing page (design §7.1). The backend `GET /api/auth/callback/{provider}`
 * completes the OIDC exchange and 302-redirects the browser here
 * (`OAUTH_POST_LOGIN_REDIRECT`, default `/auth/callback`) with the minted session JWT in the
 * URL **fragment** (`#access_token=...&session_id=...&role=user&...`). The fragment is never
 * sent to the server, so we read it client-side, persist the session, and route to the chat.
 *
 * A missing/malformed fragment (direct visit, tampered URL) shows an error with a link back
 * to login rather than silently proceeding.
 */
export default function AuthCallbackPage() {
  const router = useRouter();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const session = sessionFromFragment(window.location.hash);
    if (!session) {
      setFailed(true);
      return;
    }
    saveSession(session);
    // Drop the token-bearing fragment from history, then land on the chat.
    router.replace("/");
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
