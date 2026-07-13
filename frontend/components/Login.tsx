"use client";

import { useCallback, useState } from "react";

import {
  beginSsoLogin,
  createGuestSession,
  type Session,
  type SsoProvider,
} from "@/lib/auth";

/**
 * Login screen (design §6.2, §4 guest-login row): three ways in — SSO with Google or
 * LinkedIn (full-page redirect through the backend OIDC flow) and a one-click anonymous
 * guest session. Kept intentionally simple and consistent with the P1 chat styling
 * (constraints/non-goals: functional correctness over branding).
 *
 * The SSO buttons navigate away (the backend 302s to the provider, then redirects back to
 * `/auth/callback`), so they need no callback here. The guest button mints a session
 * in-place and reports it up via `onAuthenticated` so the parent can show the chat without
 * a reload.
 */
export interface LoginProps {
  /** Called with the new session once a guest session is created in-place. */
  onAuthenticated: (session: Session) => void;
  /** Optional banner (e.g. "Your session expired — please sign in again"). */
  message?: string;
}

const SSO_PROVIDERS: ReadonlyArray<{ id: SsoProvider; label: string }> = [
  { id: "google", label: "Continue with Google" },
  { id: "linkedin", label: "Continue with LinkedIn" },
];

export default function Login({ onAuthenticated, message }: LoginProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Consent gate (§6.22): no session is minted without accepting the ToS + privacy notice.
  // The buttons stay disabled until this is checked (UX gate); the backend is the real
  // enforcement. Guest consent is per-session; SSO consent is recorded against the user.
  const [agreed, setAgreed] = useState(false);

  const handleGuest = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const session = await createGuestSession();
      onAuthenticated(session);
    } catch {
      setError("Could not start a guest session. Please try again.");
      setBusy(false);
    }
  }, [onAuthenticated]);

  const handleSso = useCallback((provider: SsoProvider) => {
    setBusy(true);
    setError(null);
    // Full-page navigation to the backend OIDC entry point (no return to this component).
    // Consent is threaded through so the backend `/login` accepts the attempt (§6.22).
    beginSsoLogin(provider, { consent: true });
  }, []);

  // Buttons are inert until consent is given (and not while a request is in flight).
  const blocked = busy || !agreed;

  return (
    <div className="mx-auto flex h-screen w-full max-w-md flex-col justify-center p-6">
      <div className="space-y-6 rounded-xl border border-gray-200 p-8 shadow-sm">
        <header className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold">Career Coach</h1>
          <p className="text-sm text-gray-500">
            Sign in to save your history, or continue as a guest.
          </p>
        </header>

        {message ? (
          <div
            className="rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-800"
            role="status"
          >
            {message}
          </div>
        ) : null}

        {error ? (
          <div
            className="rounded-md border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700"
            role="alert"
          >
            {error}
          </div>
        ) : null}

        <label className="flex items-start gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4"
            checked={agreed}
            onChange={(event) => setAgreed(event.target.checked)}
          />
          <span>
            I agree to the{" "}
            <a href="/terms" className="text-blue-600 underline hover:text-blue-700">
              Terms of Service
            </a>{" "}
            and{" "}
            <a href="/privacy" className="text-blue-600 underline hover:text-blue-700">
              Privacy Notice
            </a>
            .
          </span>
        </label>

        <div className="space-y-3">
          {SSO_PROVIDERS.map((provider) => (
            <button
              key={provider.id}
              type="button"
              className="w-full rounded-md border border-gray-300 px-4 py-2.5 font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50"
              disabled={blocked}
              onClick={() => handleSso(provider.id)}
            >
              {provider.label}
            </button>
          ))}

          <div className="flex items-center gap-3 py-1 text-xs uppercase text-gray-400">
            <span className="h-px flex-1 bg-gray-200" />
            or
            <span className="h-px flex-1 bg-gray-200" />
          </div>

          <button
            type="button"
            className="w-full rounded-md bg-blue-600 px-4 py-2.5 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            disabled={blocked}
            onClick={() => void handleGuest()}
          >
            Continue as guest
          </button>
        </div>
      </div>
    </div>
  );
}
