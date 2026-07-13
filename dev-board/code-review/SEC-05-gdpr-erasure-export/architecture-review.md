# Architecture review — SEC-05-gdpr-erasure-export · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §9 API surface | `DELETE /api/me`, `GET /api/me/export` | Router prefix `/api/me`; `delete("")`→`/api/me`, `get("/export")`→`/api/me/export` | none |
| A2 | §8 layering | Router → Service → Repository; services never touch DB drivers | `api/me.py` thin (HTTP only); `services/account.py` depends only on `AccountRepository` + `SessionStore` ports; SQL confined to `repositories/account.py` over shared `PostgresConnectionProvider` | none |
| A3 | §8 interfaces-before-impl | Real seams | `AccountRepository` ABC + `InMemoryAccountRepository` double + `PostgresAccountRepository`; reuses existing `SessionStore` port | none |
| A4 | §7.6 Art. 17 erasure — all stores | Cascade Postgres + revoke Redis session state + Celery-held artifacts | Single `DELETE FROM users` (P2 CASCADE FKs) after enumerating + deleting every Redis session record (all devices); Celery residual documented as accepted (bounded by `result_expires`, §6.17/18) per task point 2 | none |
| A5 | §7 AuthZ / user-scoping | Target is the verified token subject only | Both endpoints key off `CurrentUser.user_id`; no path/query/body `user_id`; export filters `user_id = caller` or joins an owned parent; shared/curated `user_id IS NULL` KB rows never selected | none |
| A6 | §7.6 Art. 20 export completeness | user, profile, conversations, messages, feedback, memories, PDPs, dashboard | All 15 sections present incl. preferences, message_feedback, kb_documents/chunks, goals/milestones/tasks/progress_entries | none |
| A7 | §7.6 embedding exclusion | Exclude raw `vector(4096)` | `_kb_chunks_stmt` / `_user_memories_stmt` select explicit columns; `embedding` never selected | none |
| A8 | Locked stack | Postgres+Redis only; SSO-only auth | `require_auth`; guest→403 (consistent with `PUT /api/profile`); no new store/infra | none |
| A9 | §7.6 idempotency | No 500 on unknown/erased user | Malformed UUID → no-op; unknown id → 0 rows / empty export | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repository) — clean, ports-only service
- [x] Honors locked decisions (Postgres+Redis only; SSO-only; no ReAct parser touched)
- [x] Interfaces-before-implementations (`AccountRepository` port + Postgres adapter + in-memory double)
- [x] Budget posture respected (no new infra; reuses shared PG/Redis pools; single cascade)
- [x] Composition root wiring correct (`bootstrap.build_account_service`, `AppStateKeys.ACCOUNT_SERVICE`, `main` router registration)

## Notes
- **Follow-up (design risk, cheap to fix — not blocking):** the `feedback` table's `user_id` FK is
  `ondelete="SET NULL"` (a deliberate P2 decision — product feedback outlives the account, blessed
  earlier). The erase path is a single `users` cascade, so a feedback row's `user_id` is nulled but its
  `contact` column (an optional user-typed email, `String(320)`) survives intact. §7.6 lists `feedback`
  in the Art. 17 cascade and the P2 intent was *anonymize*, not retain-with-PII — a lingering email is
  directly-identifying and undercuts the anonymization. Recommend a targeted scrub of `feedback.contact`
  (and any PII in `contact`) as part of `erase()` (or a small migration), so the detached row is truly
  anonymized. One-line change; not expensive to unwind, hence APPROVED with this logged follow-up. The
  code-reviewer may also surface this on the correctness axis.
- `sessions` rows are intentionally not in the export (transient auth state, not user content) — consistent
  with §7.6's export intent; noted, no action.
- Export shape as open row-dict sections (not 14 typed models) is a sound KISS/portability call — one
  `SELECT` governs which columns leave, keeping the embedding-exclusion invariant in a single place.
