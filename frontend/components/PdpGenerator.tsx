"use client";

import { useCallback, useState } from "react";
import Link from "next/link";

import {
  beginSsoLogin,
  upgradeGuestToSso,
  type Session,
  type SsoProvider,
} from "@/lib/auth";
import {
  generatePdp,
  PdpApiError,
  triggerDownload,
  type PdpDeliveryStatus,
} from "@/lib/pdp";
import { trackEvent } from "@/lib/analytics";

/**
 * PDP generation surface (design §5.2 / §9; backend P7-03). A logged-in user enters a career goal
 * (+ optional target date / context) and downloads a generated Personal Development Plan PDF —
 * **without ever re-uploading a CV**: the plan is built from their stored structured profile (P5).
 *
 * Mirrors v1's `PDPDialog` fields/labels/flow **minus the CV-upload field** (the profile is already
 * stored). The request is a synchronous, potentially multi-second LLM call (P7-03) — no polling,
 * just a disabled/spinner in-flight state. Every backend outcome maps to a distinct UI state:
 *   - `200` → download the PDF (object URL + synthetic `<a download>` click, matching v1's UX),
 *   - `200` + `X-PDP-Status: role_profile_missing` → an inline "profile-based only" notice,
 *   - `422` → "upload a CV first" pointing at the profile page, `502` → "try again",
 *     `429` → rate-limit back-off, `401` → prompt sign-in (all via {@link PdpApiError.status}).
 *
 * A **guest** (P7-03 rejects guests with 403) never sees the form — they get a sign-in prompt that
 * preserves their session across the upgrade (mirrors `UpgradePrompt`'s guest pattern).
 */
export interface PdpGeneratorProps {
  /** The current session (guest → sign-in gate; user → the form). */
  session: Session;
}

type Phase = "idle" | "loading" | "success" | "error";

const SSO_PROVIDERS: ReadonlyArray<{ id: SsoProvider; label: string }> = [
  { id: "google", label: "Sign in with Google" },
  { id: "linkedin", label: "Sign in with LinkedIn" },
];

interface PdpError {
  status: number | null;
  message: string;
}

const GENERIC_ERROR = "Something went wrong generating your plan. Please try again.";

/** Today's date (`YYYY-MM-DD`) — the `min` for the target-date picker (mirrors v1). */
function todayIso(): string {
  return new Date().toISOString().split("T")[0];
}

export default function PdpGenerator({ session }: PdpGeneratorProps) {
  if (session.role === "guest") {
    return <GuestGate />;
  }
  return <PdpForm />;
}

/**
 * The sign-in gate shown to a guest (P7-03 → 403 for guests). Mirrors `UpgradePrompt`'s guest
 * pattern: offers Google/LinkedIn sign-in that *preserves the current guest session* via a
 * single-use upgrade ticket ({@link upgradeGuestToSso}), falling back to a plain login.
 */
function GuestGate() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpgrade = useCallback(async (provider: SsoProvider) => {
    setBusy(true);
    setError(null);
    try {
      await upgradeGuestToSso(provider);
    } catch {
      try {
        // The guest already accepted the consent gate at session start (§6.22).
        beginSsoLogin(provider, { consent: true });
      } catch {
        setError("Could not start sign-in. Please try again.");
        setBusy(false);
      }
    }
  }, []);

  return (
    <section
      className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-5 text-sm text-amber-900"
      aria-labelledby="pdp-guest-heading"
      data-testid="pdp-guest-gate"
    >
      <h2 id="pdp-guest-heading" className="text-lg font-semibold">
        Sign in to generate a development plan
      </h2>
      <p>
        A Personal Development Plan is built from your stored profile, so it needs an account.
        Sign in to generate and download your plan — your current session carries over.
      </p>

      {error ? (
        <p className="text-red-700" role="alert">
          {error}
        </p>
      ) : null}

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
      </div>
    </section>
  );
}

/** The PDP request form for a logged-in user. */
function PdpForm() {
  const [careerGoal, setCareerGoal] = useState("");
  const [additionalContext, setAdditionalContext] = useState("");
  const [targetDate, setTargetDate] = useState("");

  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<PdpError | null>(null);
  const [deliveryStatus, setDeliveryStatus] = useState<PdpDeliveryStatus | null>(null);

  const busy = phase === "loading";

  const handleSubmit = useCallback(async () => {
    const goal = careerGoal.trim();
    if (!goal || busy) {
      return;
    }
    setPhase("loading");
    setError(null);
    setDeliveryStatus(null);
    // Engagement event (§6.27): booleans for which optional fields were used — never their text.
    trackEvent("generate_pdp", {
      has_target_date: Boolean(targetDate),
      has_context: Boolean(additionalContext.trim()),
    });
    try {
      const result = await generatePdp({
        careerGoal: goal,
        targetDate: targetDate || undefined,
        additionalContext: additionalContext.trim() || undefined,
      });
      triggerDownload(result.blob, result.filename);
      setDeliveryStatus(result.status);
      setPhase("success");
    } catch (err) {
      if (err instanceof PdpApiError) {
        setError({ status: err.status, message: err.message });
      } else {
        setError({ status: null, message: GENERIC_ERROR });
      }
      setPhase("error");
    }
  }, [additionalContext, busy, careerGoal, targetDate]);

  return (
    <section
      className="space-y-5 rounded-xl border border-gray-200 p-5"
      aria-labelledby="pdp-heading"
      data-testid="pdp-generator"
    >
      <header className="space-y-1">
        <h2 id="pdp-heading" className="text-lg font-semibold">
          Generate a development plan
        </h2>
        <p className="text-sm text-gray-500">
          Build a Personal Development Plan from your stored profile — no need to re-upload your
          CV. We&apos;ll generate a styled PDF you can download.
        </p>
      </header>

      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          void handleSubmit();
        }}
      >
        <div className="space-y-1">
          <label htmlFor="pdp-goal" className="block text-sm font-medium text-gray-700">
            Set your career goal <span className="text-red-600">*</span>
          </label>
          <textarea
            id="pdp-goal"
            className="min-h-[80px] w-full resize-y rounded-md border border-gray-300 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Describe your career aspirations and goals…"
            value={careerGoal}
            disabled={busy}
            onChange={(event) => setCareerGoal(event.target.value)}
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="pdp-context" className="block text-sm font-medium text-gray-700">
            Any additional context?
          </label>
          <textarea
            id="pdp-context"
            className="min-h-[80px] w-full resize-y rounded-md border border-gray-300 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Any specific skills, industries, or preferences to mention…"
            value={additionalContext}
            disabled={busy}
            onChange={(event) => setAdditionalContext(event.target.value)}
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="pdp-date" className="block text-sm font-medium text-gray-700">
            Goal target date
          </label>
          <input
            id="pdp-date"
            type="date"
            className="w-full rounded-md border border-gray-300 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={targetDate}
            min={todayIso()}
            disabled={busy}
            onChange={(event) => setTargetDate(event.target.value)}
          />
        </div>

        <button
          type="submit"
          className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          disabled={!careerGoal.trim() || busy}
        >
          {busy ? "Generating…" : "Generate PDP"}
        </button>
      </form>

      {busy ? (
        <div
          className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
          role="status"
          aria-live="polite"
          data-testid="pdp-progress"
        >
          <span
            className="h-3 w-3 animate-spin rounded-full border-2 border-amber-400 border-t-transparent"
            aria-hidden="true"
          />
          <span>Generating your development plan — this can take a moment…</span>
        </div>
      ) : null}

      {phase === "success" ? (
        <div className="space-y-2" data-testid="pdp-success-block">
          <div
            className="rounded-md border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-800"
            role="status"
            data-testid="pdp-success"
          >
            Your development plan was generated and downloaded.
          </div>
          {deliveryStatus === "role_profile_missing" ? (
            <div
              className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800"
              data-testid="pdp-role-missing-notice"
            >
              We haven&apos;t mined market requirements for this role yet, so your plan is based on
              your profile only. Explore the role in{" "}
              <Link href="/roles" className="font-medium underline hover:text-blue-900">
                Roles
              </Link>{" "}
              to gather market data.
            </div>
          ) : null}
        </div>
      ) : null}

      {phase === "error" && error ? (
        <div
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
          data-testid="pdp-error"
        >
          {error.message}
          {error.status === 422 ? (
            <>
              {" "}
              <Link href="/profile" className="font-medium underline hover:text-red-800">
                Go to your profile
              </Link>
              .
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
