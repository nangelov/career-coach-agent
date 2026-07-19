---
name: project-fk-store-owning-ids-not-caller-session
description: When a new row FKs to sessions/users, persist the resource's owning ids (from the joined parent), not the caller's transient session_id
metadata:
  type: project
---

When inserting a row that has an FK to `sessions` (and/or `users`), persist the ids of the
**owning parent resource** (fetched via the ownership join), not the caller's
`CurrentUser.session_id`.

**Why:** A logged-in user's *current* session can be a fresh/Redis-only session that was never
written to Postgres `sessions`. Keying the new row on `current_user.session_id` then violates
the FK (`insert or update ... violates foreign key constraint "..._session_id_fkey"`). The
owning conversation's `session_id`/`user_id` (which you already SELECT for the ownership check)
are guaranteed present. Hit this on P9-01 message_feedback: `record()` first stored the caller's
session_id and the different-session integration test blew up.

**How to apply:** In the ownership-check query, also select the parent's `session_id`/`user_id`
and use *those* in the INSERT/upsert `.values()` + `on_conflict_do_update` set. After the
ownership check they equal the caller anyway, so nothing leaks — you just get FK-safe ids.
Related: [[project-cascade-delete-test-completeness]], [[project-auth-protected-endpoint-tests]].
