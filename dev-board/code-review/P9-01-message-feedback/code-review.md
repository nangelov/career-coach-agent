# Code review — P9-01-message-feedback · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | services/message_feedback.py:155 vs repositories/message_feedback_store.py:134 | `list_recent_downvotes` clamps `limit` differently across the two port impls: in-memory uses `rows[:max(0, limit)]` (limit≤0 → empty) while Postgres uses `.limit(max(1, limit))` (limit≤0 → 1 row). The test double can therefore mask a boundary bug in the real adapter for the P9-03 consumer. | Align the clamp in both impls (pick one contract for limit≤0), or assert `limit >= 1` at the port. Non-gating; no current caller passes limit≤0. |
| C2 | nit | api/message_feedback.py:52 | No rate-limit dependency on the capture endpoint; an authenticated caller can repeatedly POST for messages they own (each request = join + upsert). Bounded (one row per message, guests capped at 10 messages) and consistent with unrate-limited dashboard CRUD. | Optional: consider a light per-session cap in a later hardening pass. Not required here. |

## Notes
- Correctness/security are sound. Ownership is enforced in the store (not the router): missing message and not-owned both collapse to a single `None` → uniform 404, so the endpoint can't be used to probe another user's `message_id`s. Identity comes only from the verified token (`require_auth`), never the body; `message_id` is a path param. Logged-in ownership keys on `user_id` (survives a new session), guests on `session_id`.
- Persisting the message's *own* conversation `user_id`/`session_id` (not the caller's fresh/Redis-only session) is the right call — it avoids the `message_feedback_session_id_fkey` violation and cannot leak since owner == caller after the check. Well documented.
- Idempotency is correct and atomic: `UNIQUE(message_id)` (migration 0009) + `ON CONFLICT (message_id) DO UPDATE`, restamping `created_at` so "recent down-votes" reflects the latest submission. Migration 0009 chains cleanly on 0008 (current head), correctly drops the 0002 `ix_message_feedback_message_id` and adds the unique constraint; `alembic check` reports no drift.
- Layering respected (Router → Service port → Postgres adapter), mirroring `ProfileStore`/`FeedbackReader`. Read seams `get_for_message` / `list_recent_downvotes` are ready for the P9-03 learn step; scope correctly excludes LangMem/demotion/frontend.
- Guest feedback is supported at the store level (session ownership) but is effectively a no-op in production because guest message history is Redis-only and never lands in `messages` (join → 404). This matches the locked "guests get no persisted history" design decision and is explicitly acknowledged; the integration test seeds a guest message directly to prove the store logic. No action needed.
- Tests are thorough: happy up/down, idempotent resubmit, 404-unknown, 404-not-owned (user and guest), 401-unauth, 422-invalid-rating; plus live-Postgres integration for ownership over `messages`→`conversations`, cross-session ownership, and downvote listing. Ran `tests/test_message_feedback_api.py` locally → 7 passed; engineer reports full suite 819 passed / 1 pre-existing skip.
