# Architecture review — P3-05-admin-feedback-auth · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §7 AuthZ | v1 `GET /get-feedback?key=<HF_TOKEN>` (LLM-token-in-query-string) replaced with proper admin auth | `GET /api/feedback` gated by `require_admin` (session JWT + `users.is_admin`); no query-string secret anywhere | none |
| A2 | §8 structure | code lands in the right module (`api/`, `services/`, `repositories/`, `schemas/`, `security/`) | router `api/feedback.py`, port `services/feedback.py`, adapter `repositories/feedback_store.py`, contract `schemas/feedback.py`, gate `security/dependencies.py` | none |
| A3 | Layering Router→Service/Port→Repository | thin router; no driver/repo types in router; DB only via shared PG provider | router imports only port + schemas + deps + composition root; adapter uses `PostgresConnectionProvider.session()`, no ad-hoc engines | none |
| A4 | Interfaces-before-implementations | narrow port + Postgres adapter; admin lookup on the *existing* `UserStore` port | `FeedbackReader` ABC (+ in-memory double) with Postgres adapter; `UserStore.is_admin` added to the one users-table port (not a 2nd adapter) — DRY/SoC | none |
| A5 | §4 data ownership | product feedback in Postgres `feedback` table; Postgres+Redis only | `PostgresFeedbackReader` reads §4 `Feedback`; no new store introduced | none |
| A6 | §4 GDPR posture | free-text `feedback` FKs `ON DELETE SET NULL` (outlives account) | `FeedbackEntry.user_id/session_id` optional to reflect the SET NULL detach; adapter maps null-safe | none |
| A7 | Migration sequencing | additive, ordered after 0004, backfill-safe | `0005` revises `0004`; `is_admin` Boolean NOT NULL `server_default false()` backfills existing rows; no env.py autogen exclusion needed (no pgvector) | none |
| A8 | SSO-only, no self-service escalation (§7.1) | admin granted out-of-band; no route mutates the flag; new accounts non-admin | `server_default false`; no writer route; grant/revoke via documented SQL (`docs/admin-access.md` + migration docstring) | none |
| A9 | Fail-closed authz | unknown/guest caller denied | guest (`user_id is None`) short-circuits; malformed/missing id → `is_admin=False`; 401 (no token) distinct from 403 (authed non-admin) | none |
| A10 | §9 API table | `POST /api/feedback` is submit; admin read is the v1 replacement | `GET /api/feedback` (read) co-exists with the future `POST` (submit) on same path/different method — task explicitly sanctioned this path; wrapper response leaves room for paging | none (submit path is a separate task, correctly out of scope) |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service/Port→Repository)
- [x] Honors locked decisions (Postgres+Redis only; SSO-only session JWT; no shared-secret auth; no ReAct parser touched)
- [x] Interfaces-before-implementations (`FeedbackReader` port; `UserStore` extended, not duplicated)
- [x] Budget posture respected (free/OSS/self-hosted — Postgres read only)

## Notes
- Consistent with the blessed P3 auth/session seam and P3-04 authz rulings: identity comes from
  the verified token (never the body), the gate is a reusable dependency in `security/`, and
  privilege is re-checked per request against the DB (not baked into the token) so a revoke takes
  effect on the next request. `require_admin` composing on `require_auth` gives the correct 401-vs-403
  split.
- `is_admin` lives on the single `users`-table port rather than a second adapter — the right DRY/SoC
  call and the pattern any future admin-only endpoint should reuse.
- The `get_user_store` / `get_feedback_reader` lazy-cache-on-`app.state` dependencies repeat the
  established `getattr → build → setattr` idiom used by the other P3 deps; this is the accepted
  house pattern, not a new deviation.
- Follow-up (non-blocking, future task): when `POST /api/feedback` (submit) lands, keep the admin
  read and the public submit clearly separated on the shared path; the `FeedbackListResponse`
  wrapper already leaves room to add paging without a breaking change.
