/**
 * Policy version metadata for the Privacy Notice + Terms of Service pages (design §6.22 / §7.6).
 *
 * This literal MUST stay in sync with the backend's single source of truth,
 * `settings.CONSENT_POLICY_VERSION` in `backend/app/config.py` (default `"2026-07-13"`).
 * That constant drives the consent gate (no session is minted without accepting this
 * version) and is the re-consent mechanism when bumped. We hardcode the same string here
 * rather than adding a public config endpoint: the notice text and the version change
 * together in the same commit (SEC-07), so a shared literal with this cross-reference is
 * the simplest thing that stays correct (KISS / avoid new API surface — task constraint).
 *
 * When the policy text changes: bump BOTH this value and `CONSENT_POLICY_VERSION`.
 */
export const POLICY_VERSION = "2026-07-13";

/**
 * Human-readable "last updated" date shown on both legal pages. Kept identical to the
 * version above (the version IS a date) but exposed separately so a future switch to a
 * semver-style version wouldn't lose the display date.
 */
export const POLICY_LAST_UPDATED = "13 July 2026";
