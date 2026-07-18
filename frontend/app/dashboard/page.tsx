"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import Dashboard from "@/components/Dashboard";
import Login from "@/components/Login";
import { fetchSession, type Session } from "@/lib/auth";

/**
 * Dashboard route (design §5.2 / §8 App Router): the living Personal Development Plan — a
 * goals/milestones/tasks board with progress/streak charts, % to target date, and the approve/reject
 * surface for AI-proposed rows. Consumes the P8-02 human CRUD API only.
 *
 * Reachable from the chat header. Like the chat/roles/profile/pdp routes, the session is hydrated
 * from the httpOnly cookie via the BFF `GET /api/auth/session` (SEC-04); a visitor with no session
 * yet gets the login screen (which mints a guest session). A **guest** session reaches the page but
 * sees a sign-in gate inside {@link Dashboard} (the dashboard requires an account, §5.2).
 */
export default function DashboardPage() {
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
        <h1 className="text-xl font-semibold">Your dashboard</h1>
        <Link
          href="/"
          className="rounded-md border border-gray-300 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Back to chat
        </Link>
      </header>

      <Dashboard session={session} />
    </div>
  );
}
