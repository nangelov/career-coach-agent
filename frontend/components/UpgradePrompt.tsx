"use client";

import { useCallback, useState } from "react";

import {
  beginSsoLogin,
  upgradeGuestToSso,
  type Session,
  type SsoProvider,
} from "@/lib/auth";

/**
 * "Upgrade to continue" prompt shown when the backend returns a rate-limit rejection
 * (HTTP 429) instead of a raw error (design §5 guest-login: *"exceeding either prompts
 * upgrade"*, §6.8).
 *
 * For a **guest** it offers Google/LinkedIn sign-in that *preserves the current session*
 * via a single-use upgrade ticket ({@link upgradeGuestToSso}), so the conversation carries
 * over to the new account (§4 upgrade-to-account). For a **logged-in user** who simply hit
 * their generous window limit, there is nothing to upgrade — it just shows the back-off
 * message and a dismiss.
 */
export interface UpgradePromptProps {
  /** The current session (guest → offer upgrade; user → back-off only). */
  session: Session;
  /** The backend's upgrade-prompting `detail` message. */
  message: string;
  /** Dismiss the prompt (e.g. the user waits out the window). */
  onDismiss: () => void;
}

const SSO_PROVIDERS: ReadonlyArray<{ id: SsoProvider; label: string }> = [
  { id: "google", label: "Sign in with Google" },
  { id: "linkedin", label: "Sign in with LinkedIn" },
];

export default function UpgradePrompt({
  session,
  message,
  onDismiss,
}: UpgradePromptProps) {
  const isGuest = session.role === "guest";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpgrade = useCallback(
    async (provider: SsoProvider) => {
      setBusy(true);
      setError(null);
      try {
        // Preserve the guest conversation across to the new account. If minting the ticket
        // fails, fall back to a plain login rather than blocking the user.
        await upgradeGuestToSso(provider);
      } catch {
        try {
          // The guest already accepted the consent gate at session start (§6.22), so the
          // fallback plain login is consented too — thread the flag or the backend rejects it.
          beginSsoLogin(provider, { consent: true });
        } catch {
          setError("Could not start sign-in. Please try again.");
          setBusy(false);
        }
      }
    },
    [],
  );

  return (
    <div
      className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
      role="alert"
      data-testid="upgrade-prompt"
    >
      <p>{message}</p>

      {error ? (
        <p className="text-red-700" role="alert">
          {error}
        </p>
      ) : null}

      {isGuest ? (
        <div className="flex flex-wrap gap-2">
          {SSO_PROVIDERS.map((provider) => (
            <button
              key={provider.id}
              type="button"
              className="rounded-md bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              disabled={busy}
              onClick={() => void handleUpgrade(provider.id)}
            >
              {provider.label}
            </button>
          ))}
          <button
            type="button"
            className="rounded-md border border-amber-300 px-3 py-1.5 font-medium text-amber-800 hover:bg-amber-100"
            onClick={onDismiss}
          >
            Dismiss
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="rounded-md border border-amber-300 px-3 py-1.5 font-medium text-amber-800 hover:bg-amber-100"
          onClick={onDismiss}
        >
          Dismiss
        </button>
      )}
    </div>
  );
}
