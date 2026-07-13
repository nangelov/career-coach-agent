"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import Login from "@/components/Login";
import RoleRequirements from "@/components/RoleRequirements";
import { fetchSession, type Session } from "@/lib/auth";

/**
 * Roles route (design §5.6 / §8 App Router): the market-requirements surface — a target-role
 * search rendering frequency-ranked, cited requirements plus a logged-in user's read-only skills
 * gap. Explicitly **not** a job board (§1.1): no listings, no apply, no save/track.
 *
 * Reachable from the chat header. Like the chat/profile routes, the session is hydrated from the
 * httpOnly cookie via the BFF `GET /api/auth/session` (SEC-04); a visitor with no session yet gets
 * the login screen (which mints a guest session). `/requirements` needs no account, so a **guest**
 * session can browse requirements — only the personal gap is gated to logged-in users
 * (handled inside {@link RoleRequirements}).
 */
export default function RolesPage() {
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
        <h1 className="text-xl font-semibold">Role requirements</h1>
        <Link
          href="/"
          className="rounded-md border border-gray-300 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Back to chat
        </Link>
      </header>

      <RoleRequirements session={session} />
    </div>
  );
}
