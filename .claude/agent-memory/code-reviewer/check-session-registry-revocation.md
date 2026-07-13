---
name: check-session-registry-revocation
description: Revoking "all a user's sessions" must enumerate from Redis, not the lazily-populated Postgres sessions table
metadata:
  type: project
---

When a task revokes/enumerates **all of a user's live sessions** (GDPR erasure SEC-05, "logout everywhere", admin ban), check the enumeration source.

**Fact:** Live logged-in sessions are the **Redis** `SessionRecord` (key `session:record:<session_id>`), created at login in `auth.py::_resolve_session`. The Postgres `sessions` table row is created **lazily** — only on the first persisted chat turn (`repositories/conversation_store.py::persist_turn` `pg_insert(Session).on_conflict_do_nothing`, and `guest_upgrade._backfill` only when the guest had a transcript). So a user who logged in but hasn't chatted (or on a fresh device) has a Redis session but **no Postgres `sessions` row**.

**Why it bites:** `SessionAuthenticator.authenticate` only checks the Redis record exists (and JWT sig/exp) — it never re-checks the user still exists in Postgres. So enumerating sessions from the Postgres `sessions` table misses live sessions; those Redis records aren't revoked, and the erased user's bearer token keeps authenticating with a dangling `user_id` until `JWT_EXPIRE_MINUTES` (default 60) / record TTL (default 24h).

**How to apply:** Gate (blocker) any "revoke all sessions" that reads the Postgres `sessions` table as the registry. Correct sources: a per-user Redis session index written at login/upgrade, or persisting the Postgres row at login so it's complete. Also flag tests that seed a Postgres `sessions` row directly — they give false confidence and won't catch the real login-shaped gap. Related: [[check-auth-session-jwt-tasks]].
