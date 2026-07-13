---
name: project-session-registry-authority
description: Redis SessionStore is the authoritative live-session registry; Postgres sessions is lazy — enumerate per-user sessions from Redis, not Postgres
metadata:
  type: project
---

The Redis `SessionStore` (`app/services/session_store.py` port + `RedisSessionStore` in
`app/repositories/redis.py`) is the **authoritative registry of live sessions**. The Postgres
`sessions` table is only **lazily** populated — a row is written on the first *persisted* chat
turn (`conversation_store.persist_turn` / guest_upgrade backfill), NOT at login. So a
just-logged-in device that hasn't chatted has a Redis session record but **no** Postgres row.

**Why:** SEC-05 GDPR erasure originally enumerated the Postgres `sessions` table to revoke a
user's Redis sessions on `DELETE /api/me`, which missed every device that never persisted a
turn — its bearer token kept authenticating until JWT expiry (code-reviewer blocker).

**How to apply:** For any "all live sessions for user X" operation (erasure, force-logout,
session listing), enumerate from Redis via `SessionStore.list_user_sessions(user_id)` — backed
by the per-user index set `session:user:<user_id>` (maintained on `create` when the record has a
`user_id`, cleaned on `delete`). Login (`SsoAuthService._resolve_session`) and guest-upgrade
(`GuestUpgradeService.upgrade`) both route through `SessionStore.create` with a user-bearing
record, so the index is complete. Never treat the Postgres `sessions` table as a complete
session registry.

Related: `feedback` FK is `ON DELETE SET NULL` (product feedback outlives the account) — on
erasure, also scrub `feedback.contact` (a user-typed email = PII) to NULL in the same
transaction, or the "anonymized" row still leaks directly-identifying data. See
[[project-abc-port-extension-breaks-fakes]] (adding `list_user_sessions` to the port touched
both concrete stores — only two impls, no test fakes subclass it).
