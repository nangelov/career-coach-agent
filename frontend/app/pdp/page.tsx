"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import Login from "@/components/Login";
import PdpGenerator from "@/components/PdpGenerator";
import { fetchSession, type Session } from "@/lib/auth";

/**
 * PDP route (design §5.2 / §8 App Router): the Personal Development Plan generation surface —
 * a logged-in user enters a career goal (+ optional target date / context) and downloads a
 * generated PDF built from their **stored** profile (P5/P7-03), with no CV re-upload.
 *
 * Reachable from the chat header. Like the chat/roles/profile routes, the session is hydrated from
 * the httpOnly cookie via the BFF `GET /api/auth/session` (SEC-04); a visitor with no session yet
 * gets the login screen (which mints a guest session). A **guest** session reaches the page but
 * sees a sign-in gate inside {@link PdpGenerator} (P7-03 rejects guests with 403).
 */
export default function PdpPage() {
  const [session, setSession] = useState<Session | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

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
        <h1 className="text-xl font-semibold">Development plan</h1>
        <Link
          href="/"
          className="rounded-md border border-gray-300 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Back to chat
        </Link>
      </header>

      <PdpGenerator session={session} />
    </div>
  );
}
