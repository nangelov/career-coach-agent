"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import CvUpload from "@/components/CvUpload";
import Login from "@/components/Login";
import ProfileView from "@/components/ProfileView";
import { fetchSession, type Session } from "@/lib/auth";

/**
 * Profile route (design §5.1 / §8 App Router): hosts the CV upload + parse-progress surface and
 * the structured-profile view/edit, reachable from the chat header. Auth-gated like the chat
 * (P3-06): the session is hydrated from the httpOnly cookie via the BFF `GET /api/auth/session`
 * (SEC-04), and an unauthenticated visitor gets the login screen. When a CV parse succeeds, `onParsed` bumps a
 * reload key so the profile view re-fetches the freshly persisted profile without a page reload.
 */
export default function ProfilePage() {
  const [session, setSession] = useState<Session | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // Hydrate the session from the httpOnly cookie via the BFF (SEC-04 — no localStorage).
  useEffect(() => {
    let cancelled = false;
    void fetchSession()
      .then((next) => {
        if (!cancelled) {
          setSession(next);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setAuthChecked(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleParsed = useCallback(() => {
    setReloadKey((key) => key + 1);
  }, []);

  // Avoid a hydration flash / premature login screen before the session is resolved.
  if (!authChecked) {
    return null;
  }

  if (!session) {
    return <Login onAuthenticated={setSession} />;
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-6 p-4">
      <header className="flex items-center justify-between border-b border-gray-200 pb-3">
        <h1 className="text-xl font-semibold">Your profile</h1>
        <Link
          href="/"
          className="rounded-md border border-gray-300 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Back to chat
        </Link>
      </header>

      <CvUpload session={session} onParsed={handleParsed} />
      <ProfileView session={session} reloadKey={reloadKey} />
    </div>
  );
}
