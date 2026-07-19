"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import Login from "@/components/Login";
import MemoryPanel from "@/components/MemoryPanel";
import { fetchSession, type Session } from "@/lib/auth";

/**
 * Memory route (design §5.4 / §8 App Router): hosts the "what the coach knows about you" panel —
 * explicit preferences (view/edit) + learned memories (view/delete) — reachable from the chat
 * header. Auth-gated like the other feature pages (mirrors `app/profile/page.tsx`): the session is
 * hydrated from the httpOnly cookie via the BFF `GET /api/auth/session` (SEC-04), and an
 * unauthenticated visitor gets the login screen. A signed-in guest sees the panel's own
 * account-only informative state (§5.4 / P9-07).
 */
export default function MemoryPage() {
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
        <h1 className="text-xl font-semibold">Memory</h1>
        <Link
          href="/"
          className="rounded-md border border-gray-300 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Back to chat
        </Link>
      </header>

      <MemoryPanel session={session} />
    </div>
  );
}
