/**
 * GA4 (gtag.js) product-analytics helper (design §6.27) — a thin, SSR-safe wrapper over
 * `window.gtag('event', ...)`.
 *
 * Ported from the v1 CRA `window.gtag?.(...)` pattern (`legacy-code/.../ChatBot.tsx`) into the v2
 * App Router. The rules that matter here:
 *
 *   - **Env-gated:** analytics is fully disabled unless `NEXT_PUBLIC_GA_MEASUREMENT_ID` is set.
 *     With it unset, {@link trackEvent}/{@link trackPageview} are no-ops and `<Analytics>` injects
 *     no script — zero network calls, no console errors.
 *   - **Consent-gated at the injection site**, not here: the `gtag.js` script is only loaded once
 *     an active {@link import("./auth").Session} exists (see `components/Analytics.tsx`), which
 *     implies the §6.22 consent gate was already accepted server-side. This module never loads the
 *     script; it only pushes events onto an already-initialised `window.gtag`.
 *   - **No PII, ever:** event parameters are non-content metadata only (counts, booleans, roles,
 *     ratings, UUID ids). {@link sanitizeParams} is a runtime backstop that drops
 *     free-text-shaped values so a future caller cannot accidentally leak a chat message or CV
 *     text through a parameter.
 */

declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
    dataLayer?: unknown[];
  }
}

/** The GA4 Measurement ID, or "" when analytics is disabled. Read once at module load. */
export const GA_MEASUREMENT_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID ?? "";

/** True only when a Measurement ID is configured — the master on/off switch for all GA4 code. */
export function isAnalyticsEnabled(): boolean {
  return GA_MEASUREMENT_ID.length > 0;
}

/**
 * The closed set of engagement events we emit. Mirrors the v1 button-click events (`click-*`),
 * expanded to the v2 surfaces (chat, CV, PDP, message feedback, dashboard). Keeping it a union
 * stops ad-hoc event names drifting in over time.
 */
export type AnalyticsEvent =
  | "send_message"
  | "stop_generation"
  | "upload_cv"
  | "generate_pdp"
  | "message_feedback"
  | "dashboard_goal_create"
  | "dashboard_item_create"
  | "dashboard_proposal_approve"
  | "dashboard_proposal_reject";

/** Parameter values must be non-content primitives (counts / booleans / short ids / enums). */
export type AnalyticsParamValue = string | number | boolean;
export type AnalyticsParams = Record<string, AnalyticsParamValue | undefined>;

/**
 * Max length for a string parameter value. A UUID (36) / role / rating / mime-type / path all fit
 * well under this; anything longer is assumed to be accidental free text (a chat message, CV
 * snippet, …) and is dropped rather than sent. This is the PII backstop referenced above.
 */
export const MAX_PARAM_STRING_LEN = 64;

/**
 * Drop `undefined` params and any string value that looks like free text (over
 * {@link MAX_PARAM_STRING_LEN}). Returns a plain object safe to hand to `gtag`.
 */
export function sanitizeParams(params?: AnalyticsParams): Record<string, AnalyticsParamValue> {
  const clean: Record<string, AnalyticsParamValue> = {};
  if (!params) {
    return clean;
  }
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) {
      continue;
    }
    if (typeof value === "string" && value.length > MAX_PARAM_STRING_LEN) {
      // Guard: never forward long, free-text-shaped values (message content, CV text, …).
      continue;
    }
    clean[key] = value;
  }
  return clean;
}

/**
 * Emit a GA4 custom event. No-op when analytics is disabled, on the server, or before `gtag` has
 * initialised (`window.gtag?.(...)` optional-chaining safety — matches v1). Parameters are
 * sanitised to non-content metadata.
 */
export function trackEvent(name: AnalyticsEvent, params?: AnalyticsParams): void {
  if (!isAnalyticsEnabled() || typeof window === "undefined") {
    return;
  }
  window.gtag?.("event", name, sanitizeParams(params));
}

/**
 * Emit a GA4 pageview for a client-side (App Router) navigation. The *initial* pageview is sent by
 * the `gtag('config', ...)` call in `<Analytics>`; this covers subsequent route changes. `path` is
 * a URL path (not PII).
 */
export function trackPageview(path: string): void {
  if (!isAnalyticsEnabled() || typeof window === "undefined") {
    return;
  }
  window.gtag?.("event", "page_view", { page_path: path });
}
