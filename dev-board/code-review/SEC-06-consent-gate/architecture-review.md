# Architecture review — SEC-06-consent-gate · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Consent gate on session creation (§6.22 / §7.6) | No session minted without ToS+privacy acceptance | Guest start and SSO `begin_login` both raise `ConsentRequired` before minting/redirect; `POST /guest` fails closed on missing body | none |
| A2 | SSO consent recorded against the user with **policy version + timestamp** (§6.22) | `users` row carries version + accepted-at | Migration `0006` adds nullable `consent_policy_version`+`consent_accepted_at`; callback writes both on every login (insert **and** conflict-update) | none |
| A3 | Guest consent is **per-session, not durable** (§6.22, §6.18) | Guest holds nothing in Postgres; consent per guest-start | Guest gate re-checked every start; version stamped only on the transient Redis `SessionRecord`; no guest Postgres column | none |
| A4 | Re-prompt on policy bump (§6.22) | Stale version re-collected at next login | Every login re-records via upsert → stale version overwritten; login screen always re-shows checkbox; no mid-session force-logout (documented scope boundary) | none |
| A5 | Single source of truth for policy version | One bumpable constant | `settings.CONSENT_POLICY_VERSION` (`app/config.py`), injected into both services via `from_settings` | none |
| A6 | §8 target structure + layering (Router→Service→Repo) | Enforcement in services, thin router | `ConsentRequired` raised in `services/auth.py`, mapped to 400 in `api/auth.py`; persistence in `repositories/user_store.py`; schemas in `schemas/auth.py` — no cross-layer leak | none |
| A7 | Datastores: Postgres + Redis only (locked) | Durable SSO consent in PG, guest in Redis only | Correct split; OAuth-state carrier reuses existing Redis `oauth_state_store` (no second mechanism) | none |
| A8 | Migration follows Alembic pattern (§8) | Clean up/down, nullable backfill | `0006` revises `0005`, single head, both columns nullable/no server default, downgrade drops both | none |
| A9 | Frontend §8 lib/components split | Consent flag threaded via `lib/auth.ts`, UI in `components/Login.tsx` | Checkbox + disabled buttons in Login.tsx (UX gate); `beginSsoLogin`/`createGuestSession` carry consent; BFF `guest`+`login` route handlers forward it server-side | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repo) — enforcement in services, 400 mapping in router
- [x] Honors locked decisions — Postgres+Redis only (durable SSO consent PG, guest Redis-only); SSO-only auth untouched; no new password surface
- [x] Interfaces-before-implementations — consent params added to `UserStore` ABC + both `PostgresUserStore`/`InMemoryUserStore`; `OAuthStateRecord`/`SessionRecord` schema-carried
- [x] Budget posture — no new paid dependency; reuses existing Redis txn + Postgres

## Notes
- **Blessed:** reusing `oauth_state_store` (Redis) to carry the accepted policy version across the two-request OIDC flow — correct, since `users` does not exist at `/login`. No second mechanism invented.
- **Blessed:** upsert consent params defaulting to `None` (columns nullable) so out-of-band/seed callers are unaffected — non-breaking seam, SSO flow always passes real values.
- Minor (no change required): `consent_accepted_at` is stamped at callback-completion time rather than checkbox-tick time. Acceptable — it records when the consented login completed; the version accepted is the one captured at `/login` and threaded through state.
- Minor (no change required, documented scope boundary): a returning SSO user with a live BFF cookie session won't re-see the login screen until the session expires, so a policy bump re-prompts only at next login — explicitly accepted per task step 5 / §6.22.
- ToS/privacy link targets `/terms` + `/privacy` are placeholders for SEC-07 as scoped; content correctly out of scope here.
