---
name: project-admin-authz
description: Blessed P3-05 admin-auth pattern — is_admin on users, require_admin gate, per-request DB check; the shape any future admin endpoint must reuse
metadata:
  type: project
---

P3-05 (APPROVED rev 1) established the v2 admin-authz pattern, replacing v1's
`GET /get-feedback?key=<HF_TOKEN>` (LLM-token-as-query-string-secret) with real access control.

**Why:** §7 AuthZ requires "proper admin auth"; the query-string shared secret is not an
access-control model.

**How to apply (reuse for any future admin-only endpoint):**
- Admin is a boolean `users.is_admin` column (migration 0005, Boolean NOT NULL `server_default false()`),
  NOT a JWT claim — re-checked per request against the DB so revoke takes effect next request.
- Gate = `require_admin` in `security/dependencies.py`, which **composes on `require_auth`** →
  gives the correct 401 (no/invalid token) vs 403 (authenticated non-admin) split. Guest
  (`user_id is None`) can never be admin. Fail-closed: unknown/malformed id → False, never raises.
- Admin lookup lives on the **single `UserStore` port** (`is_admin(user_id)`), not a second
  users-table adapter — DRY/SoC, `UserStore` is *the* users-table port.
- No self-service escalation: no route mutates `is_admin`; granted out-of-band via SQL
  (`docs/admin-access.md`). server_default false → new accounts never admin.
- Feedback read: narrow `FeedbackReader` port (read-only, YAGNI — submit is a separate task) +
  Postgres adapter; `GET /api/feedback` co-exists with future `POST /api/feedback` submit (§9)
  on same path/different method; response is a `FeedbackListResponse` wrapper (paging room), not
  a bare array.

Consistent with [[project-authz-ratelimit]] (identity from token not body, centralized gate) and
[[project-auth-session-seam]] (security/ pkg, per-request session verify).
